#!/bin/sh

# cd to this script dir (src namakanui/doc)
cd `dirname "$0"`
echo cd `pwd`

# modify sys.path to find src modules
export PYTHONPATH=../src:${PYTHONPATH}
echo PYTHONPATH=$PYTHONPATH

#echo pydoc namakanui
./jac_sw_pydoc3 -w namakanui
for m in `ls ../src/namakanui/*.py`; do
    module=namakanui.`basename "$m" .py`
    #echo pydoc $module
    ./jac_sw_pydoc3 -w "$module"
done

