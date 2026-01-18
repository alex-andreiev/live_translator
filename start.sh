#!/bin/bash
cd "$(dirname "$0")"

# Add cuDNN libraries to path for CUDA support
CUDNN_PATH="./venv/lib/python3.12/site-packages/nvidia/cudnn/lib"
CUBLAS_PATH="./venv/lib/python3.12/site-packages/nvidia/cublas/lib"

if [ -d "$CUDNN_PATH" ]; then
    export LD_LIBRARY_PATH="$CUDNN_PATH:$CUBLAS_PATH:$LD_LIBRARY_PATH"
fi

./venv/bin/python main.py "$@"
