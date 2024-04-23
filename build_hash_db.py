#!/bin/python3
# Copyright (c) 2021 José Manuel Barroso Galindo <theypsilon@gmail.com>

import json
import subprocess
import tempfile
import re
import os
import hashlib
from typing import Any, Dict, List, TypedDict, Tuple
import zlib
import signal
import time
import sys
from pathlib import Path

_print = print
def print(text=""):
    _print(text, flush=True)
    sys.stdout.flush()

skip_list = []

class HashData(TypedDict):
    md5: str
    size: int

class InterruptHandler:
    def __init__(self, timeout: int):
        self._timeout = timeout
        self._kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args) -> None:
        self._kill_now = True

    def should_end(self) -> bool:
        if self._timeout > 0 and int(time.time()) > self._timeout:
            print('Time is out!')
            return True

        if self._kill_now:
            print('Signal received for termination!')
            return True
        
        return False

def main() -> None:
    print('START!')

    source = os.environ['SOURCE'].strip()
    db_file = os.environ['DB_FILE'].strip()
    oneshot = "ONESHOT" in os.environ
    timeout = int(os.environ.get('TIMEOUT_MINUTES', '-1').strip()) * 60
    if timeout >= 0:
        timeout += int(time.time())

    print('source: %s' % source)
    print('db_file: %s' % db_file)
    print('timeout: %d' % timeout)

    process(source, InterruptHandler(timeout), db_file, oneshot)

    print('Done.')

def process(source: str, interrupt_handler: InterruptHandler, db_file: str, oneshot: bool) -> None:
    if re.fullmatch('https://archive[.]org/download/([-_a-z0-9.%]+)/([-_a-z0-9.%]+)[.]zip/', source.lower()):
        print('process_with_downloads')
        return process_with_downloads(source, interrupt_handler, db_file, oneshot)

    if re.fullmatch('([-_a-z0-9.%/\[\]]+)', source.lower()):
        print('process_with_metadata_query')
        return process_with_metadata_query(source, interrupt_handler, db_file, oneshot)
    
    raise Exception('Could not process source %s' % source)

def process_with_metadata_query(source: str, interrupt_handler: InterruptHandler, db_file: str, oneshot: bool) -> None:
    source_route, source_dir = split_on_first_slash(source)
    proc = subprocess.run(curl(["https://archive.org/metadata/%s" % source_route]), stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    if proc.returncode == 0:
        print('Ok')
    else:
        print("FAILED! %d" % proc.returncode)
        exit(-1)

    files = load_files(db_file)

    for description in json.loads(proc.stdout.decode())["files"]:
        if 'name' not in description:
            continue

        rom = description["name"]
        if description["format"].strip().lower() != "zip":
            print('Skip: ' + rom)
            continue
            
        if source_dir is not None and not rom.startswith(source_dir):
            print('Skip: ' + rom)
            continue

        print(rom)
        save_rom_in_files(db_file, not oneshot, files, os.path.basename(rom), {
            "md5": description["md5"].strip(),
            "size": int(description["size"].strip()),
            "fullpath": rom
        })


        if interrupt_handler.should_end():
            if oneshot: save_db_file(db_file, files)
            return
    if oneshot: save_db_file(db_file, files)

def process_with_downloads(source: str, interrupt_handler: InterruptHandler, db_file: str, oneshot: bool) -> None:
    roms = query_roms(source)
    files = load_files(db_file)
    verbose = os.environ.get('VERBOSE', 'false') == 'true'

    with tempfile.NamedTemporaryFile() as temp:
        for rom in roms:
            if rom in files or in_skip_list(files, rom):
                continue
                
            rom_size = roms[rom]

            if rom_size > 1_000_000_000:
                add_rom_to_skip_list(files, rom)
                save_db_file(db_file, files)
                continue

            rom_description = try_work_on_rom_a_few_times(rom, source, temp, rom_size, interrupt_handler, verbose)
            save_rom_in_files(db_file, not oneshot, files, rom, rom_description)

            if interrupt_handler.should_end():
                return

def in_skip_list(files, rom):
    return '0000_skip_list' in files and rom in files['0000_skip_list']

def add_rom_to_skip_list(files, rom):
    print('Skipping %s' % rom)
    if '0000_skip_list' not in files:
        files['0000_skip_list'] = []
    files['0000_skip_list'].append(rom)

def save_rom_in_files(db_file: str, do_save: bool, files: Dict[str, HashData], rom: str, rom_description: HashData) -> None:
    if rom_description is not None:
        files[Path(rom).name] = rom_description
        if do_save: save_db_file(db_file, files)

def save_db_file(db_file, files):
    with open(db_file, 'wt') as f:
        json.dump(files, f, indent=4, sort_keys=True)

def try_work_on_rom_a_few_times(rom: str, source: str, temp: Any, expected_size: int, interrupt_handler: InterruptHandler, verbose: bool) -> HashData:
    for try_index in range(3):
        rom_description = work_on_rom(rom, source, temp, expected_size, verbose)
        if rom_description is not None:
            return rom_description

        print('Try %d failed!' % try_index)

        if interrupt_handler.should_end():
            return None

        print('Waiting 5 minutes until next try...')
        time.sleep(300.0)

        if interrupt_handler.should_end():
            return None

    print('Aborting execution with errors.')
    exit(-1)

def work_on_rom(rom: str, source: str, temp: Any, expected_size: int, verbose: bool) -> HashData:
    print(rom)
    url = source + rom

    proc = subprocess.run(curl(['-o', temp.name, url], size=expected_size, verbose=verbose), stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print('Failed! %d' % proc.returncode)
        return None

    filesize = size(temp.name)
    if filesize != expected_size:
        print('File size missmatch')
        print('%s != %s' % (filesize, expected_size))
        return None

    proc = subprocess.run(['unzip', '-t', temp.name], stdout=subprocess.DEVNULL)
    if proc.returncode != 0:
        print('Wrong zip! %d' % proc.returncode)
        return None
    
    md5 = md5_calc(temp.name)
    print(md5)
    print()

    return {
        "md5": md5,
        "size": filesize
    }


def query_roms(source: str) -> Dict[str, int]:
    proc = subprocess.run(curl([source]), stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    if proc.returncode != 0:
        print('Failed! %d' % proc.returncode)
        exit(1)

    printing = False

    regex = re.compile('.*>([-_a-zA-Z0-9.]+[.]zip)<.*"size">([0-9]+)<.*')
    roms = {}
    
    for line in proc.stdout.decode().splitlines():
        if not printing and '<main id="maincontent">' in line:
            printing = True
        elif '</main>' in line:
            printing = False

        if not printing:
            continue

        match = regex.match(line.lower())
        if not match:
            continue

        roms[match.group(1)] = int(match.group(2))

    return roms

def load_files(db_file: str) -> Dict[str, HashData]:
    files = {}
    if os.path.isfile(db_file):
        with open(db_file, 'r') as f:
            files = json.load(f)

    return files

def curl(params: List[str], size=0, verbose=False) -> List[str]:
    curl_parameters = ['curl', '-L' if verbose else '-sL']
    curl_parameters.extend(os.environ.get('CURL_SECURE', '').split())
    if size > 1_000_000_000:
        curl_parameters.extend(['--header', 'X-Accel-Buffering: no'])
    curl_parameters.extend(params)
    return curl_parameters

def md5_calc(file: str) -> str:
    with open(file, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8192)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8192)
        return file_hash.hexdigest()

def split_on_first_slash(input_string) -> Tuple[str, None]:
    split_index = input_string.find('/')
    if split_index == -1:
        return input_string, None
    else:
        return input_string[:split_index], input_string[split_index+1:]

def crc32_calc(file: str) -> str:
    prev = 0
    for line in open(file,"rb"):
        prev = zlib.crc32(line, prev)
    return "%X"%(prev & 0xFFFFFFFF)

def size(file: str):
    return os.path.getsize(file)

if __name__ == "__main__":
    main()
