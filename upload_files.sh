#!/bin/sh



cd $1
for x in `find . -name "*.zip"`
do
  $2 upload retroautomate $x --keep-directories
done
