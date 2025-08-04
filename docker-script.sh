#!/bin/bash

docker run -it --rm \
--device=/dev/kfd \
--device=/dev/dri \
--group-add video \
--cap-add=SYS_PTRACE \
--security-opt seccomp=unconfined \
-v ./:/therock/src \
-v ./output-linux-portable:/therock/output \
-w /therock/src \
ghcr.io/rocm/therock_build_manylinux_x86_64:main /bin/bash -c "pip install -r requirements.txt\
&& mkdir -p /opt/rocm/bin && cp -r /therock/output/build/dist/rocm /opt && exec bash"