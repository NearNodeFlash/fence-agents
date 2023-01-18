# NNF Fencing Agent

Some notes on the NNF Fencing agent

# Build

Needs a .tarball-version file to build correctly (still trying to figure that out)

```
echo "0.0.1-nnf" > ./.tarball-version
```

The python version defaults to 2 and required several modules that are not installed. Forcing python version 3 since it includes the modules
Disabled libvirt & cpg plugins since they have undesirable build dependencies.

```
./autogen.sh
PYTHON=python3 ./configure --disable-libvirt-plugin --disable-cpg-plugin --with-agents="nnf redfish"
make
make install
```