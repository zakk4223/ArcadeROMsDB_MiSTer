#!/usr/bin/env python3


import os
import sys
import json
import subprocess
from typing import Any, Dict, List, TypedDict, Tuple
from pathlib import Path,PurePosixPath
from urllib.parse import unquote, urlparse

_print = print

def print(text=""):
    _print(text, flush=True)
    sys.stdout.flush()



def main():

    
    arcade_roms_dbj = os.environ.get('ARCADE_ROMS_DB', None)
    ia_repo_dbj = os.environ.get('IA_REPO_DB', None)
    rom_skip_list_file = os.environ.get('SKIP_LIST', None)

    rom_skip_list = []

    if not arcade_roms_dbj or not ia_repo_dbj:
        print('MISSING ENV VARS FOR DB')
        exit(-1)

    with open('arcade_sources.json', 'r') as f:
        sources = json.load(f)


    with open(arcade_roms_dbj, 'r') as f:
        arcade_db = json.load(f)

    with open(ia_repo_dbj, 'r') as f:
        ia_db = json.load(f)

    with open(rom_skip_list_file, 'r') as f:
        rom_skip_list = json.load(f)


    
    arcade_files = arcade_db['files']

    sync_info = []
    for path,rom_data in arcade_files.items():
        need_sync = False
        rom_hash = rom_data['hash']
        rom_path = rom_data['path']
        if rom_path in rom_skip_list:
            continue
        if rom_data['path'] in ia_db:
            if rom_hash != ia_db[rom_path]['md5']:
                need_sync = True
        else:
            need_sync = True


        if need_sync: 
            sync_info.append({'url': rom_data['url'], 'dlpath': rom_data['path'], 'size': rom_data['size']})
    os.mkdir('./iatmp')
    os.mkdir('./iatmp/mame/')
    os.mkdir('./iatmp/hbmame/')
    ia_login()
    for rom_info in sync_info:
        download_rom_local(rom_info, 'iatmp')

    print(sync_info)



def download_rom_local(rom_info, basedir="./"):
    dl_dest = os.path.join(basedir, rom_info['dlpath'])
    dl_dir = os.path.join(basedir, os.path.dirname(rom_info['dlpath']))
    dl_url = rom_info['url']
    dl_size = int(rom_info['size'])
    dl_user = os.environ.get('IA_USER', '')
    dl_pass = os.environ.get('IA_PASS', '')


    print(f"Downloading {dl_url} {dl_dest}")
    proc = subprocess.run(curl(['-o', dl_dest, dl_url]))

    if proc.returncode != 0:
        print('Failed! %d' % proc.returncode)
        return None

    filesize = os.path.getsize(dl_dest)
    if filesize != dl_size:
        print('File size mismatch')
        print('%s != %s' % (filesize, dl_size))
        os.remove(dl_dest)
        return None

def ia_login():
    dl_user = os.environ.get('IA_USER', '')
    dl_pass = os.environ.get('IA_PASS', '')
    subprocess.run(curl(['-X', 'POST', '--data-raw', f'username={dl_user}&password={dl_pass}&remember=true', 'https://archive.org/account/login']))

def curl(params: List[str], size=0, verbose=False) -> List[str]:
    curl_parameters = ['curl', '-L' if verbose else '-sL', '--cookie-jar', './cookie.tmp', '--cookie', './cookie.tmp']
    curl_parameters.extend(os.environ.get('CURL_SECURE', '').split())
    if size > 1_000_000_000:
        curl_parameters.extend(['--header', 'X-Accel-Buffering: no'])
    curl_parameters.extend(params)
    return curl_parameters


if __name__ == "__main__":
    main()




