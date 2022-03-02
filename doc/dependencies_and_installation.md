<!-- gfm -->

# Namakanui Dependencies and Installation

Ryan Berthold  
October 2021


## Linux

These instructions are based on a 64-bit CentOS 7.8 system (gltcanbus), kernel 3.10.0.  Other distributions will probably work similarly.


## Tornado

The existing gltcanbus install includes a copy of Tornado 2.2, but this may not be transferable to the GLT due to WindRiver licensing issues.  Be aware that without a copy of Tornado, various Makefiles will need to be modified to exclude “ppc604” and other build targets.  The copy on gltcanbus can be found in `/jac_sw/vxworks/`.


## Tcl / Tk

DRAMA wants a Tcl/Tk development package installed on the system for `tcl.h`, `libtcl.so`, etc.  E.g.:

```sh
yum install tcl-devel
yum install tk-devel
```


## `/local`

The `/local` directory holds copies of java, perl and python.  Namakanui does not actually use java or perl, but installing them will simplify the build process.

```sh
cd /
mkdir local
ln -s local local64
```

Everything in `/local` can be copied pre-built from gltcanbus, or you can download the same versions from public repositories and build them yourself.


## `/local/java`

Copy the following tarball from gltcanbus:
`/local/java/jdk1.5.0_10.tar.gz`

```sh
mkdir -p /local/java/
cp jdk1.5.0_10.tar.gz /local/java/
cd /local/java
tar -xzf jdk1.5.0_10.tar.gz
ln -s jdk1.5.0_10 jdk1.5
ln -s jdk1.5.0_10 jdk
```

## `/local/perl`

Copy the following tarball from gltcanbus:
`/local/perl-5.16-thread.tar.gz`

```sh
cp perl-5.16-thread.tar.gz /local/
cd /local
tar -xzf perl-5.16-thread.tar.gz
ln -s perl-5.16-thread perl
```

## `/local/python3`

Copy the following tarball from gltcanbus:
`/local/python3.7.1.tar.gz`

```sh
cp python3.7.1.tar.gz /local/
cd /local
tar -xzf python3.7.1.tar.gz
ln -s python3.7.1 python3
```

Note: If you choose to build python instead of copying from gltcanbus, you’ll need to install cython (using e.g. `/local/python3/bin/pip install cython`) and the pyuae project (below).


## EPICS

JCMT software uses the EPICS build system, even if Namakanui doesn’t include any EPICS IOCs.  It goes in the `/jac_sw` directory.

Copy the following tarball from gltcanbus:
`/jac_sw/epics/src/epics_t2p2_R3.13.8.tar.gz`

```sh
mkdir -p /jac_sw/epics/src
cp epics_t2p2_R3.13.8.tar.gz /jac_sw/epics/src
cd /jac_sw/epics/src
tar -xzf epics_t2p2_R3.13.8.tar.gz

cd /jac_sw/epics/src/t2p2_R3.13.8/
# To build without vxWorks, rename all the .Vx makefiles:
find . -name Makefile.Vx -exec mv {} {}_no \;

make
cp config/CONFIG_HOST_ARCH.Linux /jac_sw/epics/t2p2_R3.13.8_b64/config/
cp config/CONFIG.Host.Linux /jac_sw/epics/t2p2_R3.13.8_b64/config/

cd /jac_sw/epics/src/t2p2_extensions/
# edit Makefile.Dirs so it only builds “uae” dir
# uae/RULES_APPLIC.Build: comment out $(PERL) cmd on lines 273 and 288
cp uae/CONFIG_APPLIC /jac_sw/epics/t2p2_R3.13.8_b64/config/
cp uae/RULES_APPLIC.Build /jac_sw/epics/t2p2_R3.13.8_b64/config/
cp uae/RULES_APPLIC.Dirs /jac_sw/epics/t2p2_R3.13.8_b64/config/
make

cd /jac_sw/epics
ln -s t2p2_R3.13.8_b64 CurrentRelease
```


## DRAMA

Copy from gltcanbus:
`/jac_sw/drama/src/drama-v1.6.3_b64.tar.gz`

```sh
mkdir -p /jac_sw/drama/src
cp drama-v1.6.3_b64.tar.gz /jac_sw/drama/src
cd /jac_sw/drama/src
tar -xzf drama-v1.6.3_b64.tar.gz
cd drama-v1.6.3_b64
# To build without vxWorks, rename all the .Vx makefiles:
find . -name Makefile.Vx -exec mv {} {}_no \;
make

cd /jac_sw/drama
ln -s drama-t2p2_v1.6.3_20191205 CurrentRelease
```

Copy from gltcanbus:
`/jac_sw/drama/etc/IMP_Startup.JCMT`

```sh
mkdir -p /jac_sw/drama/etc/startup
cp IMP_Startup.JCMT /jac_sw/drama/etc
cd /jac_sw/drama/etc/startup
ln -s ../IMP_Startup.JCMT IMP_Startup
```

Note the name of the `IMP_Startup` file.  I’m not sure, but some processes may use the `IMP_Startup.<$SITE>` file directly instead of the link in the startup directory.  You’ll probably want to rename this file `IMP_Startup.GLT` and make sure `$SITE=GLT` in your environment.


## `/jac_logs`

Create log directory for DRAMA tasks:

```sh
mkdir -p /jac_logs
```


## `/jcmtdata`

Jit tasks expect to find a couple of config files on the system, even if they won’t be used by your OCS.  In particular the `jit_tasks.xml` file can override DRAMA buffer sizes for a given task.

```sh
mkdir -p /jcmtdata/ocs_configs
cd /jcmtdata/
ln -s ocs_configs ocsconfigs
```

Then copy the following files from gltcanbus to the same location on your target system:

```
/jcmtdata/orac_data/ocsconfigs/machine_table.xml
/jcmtdata/orac_data/ocsconfigs/jit_tasks.xml
```



## `/jac_sw/itsroot`

Our custom software lives in the `/jac_sw/itsroot` directories.

```sh
mkdir /jac_sw/itsroot
mkdir /jac_sw/itsroot/src
mkdir /jac_sw/itsroot/install
```


## pyuae

If you built python3 from source instead of copying it from gltcanbus, you’ll need the pyuae project.  This project installs a `jac_sw` module into the `/local/python3 site-packages`, which is used to build `jac_sw` extension modules and find modules in the `/jac_sw/itsroot/install` path.

```sh
cd /jac_sw/itsroot/src
git clone <user>@ssh.eao.hawaii.edu:/jac_sw/gitroot/pyuae.git
cd pyuae
make
```

## Itsroot projects

Our software repos do not include a top-level `Makefile` or a `config/CONFIG.Defs` file.  These files will need to be copied over from their corresponding locations on gltcanbus.

The build/install process for the following projects is as follows:

```sh
cd /jac_sw/itsroot/src
git clone <user>@ssh.eao.hawaii.edu:/jac_sw/gitroot/<project>.git
cd <project>
scp gltcanbus:/jac_sw/itsroot/src/<project>/Makefile .
scp gltcanbus:/jac_sw/itsroot/src/<project>/config/CONFIG.Defs config/
make
cd /jac_sw/itsroot/install
ln -s <project>* <project>
```

The projects are installed with a version number, e.g. `common_0p4_b64`; the last `ln` step creates softlink to the in-use version.

Follow this process for the following projects:

- common  (see notes below)
- pydrama
- adam
- namakanui


## common

Edit `jit/Makefile.Host` to replace the `cvs checkout` commands with simple copies.  Comment out lines 129 and 134 and put instead:

```makefile
cp /jac_sw/drama/src/drama-v1.6.3_b64/drama_source/dits/ditscmd.c $@
cp /jac_sw/drama/src/drama-v1.6.3_b64/drama_source/dits/ditsgetinfo.c $@
```

Without the `common` install directory in your `$PATH`, the build will fail on memTrack.  Once it does, create the `common` softlink in the `/jac_sw/itsroot/install` directory and then add it to your `$PATH` environment variable.

There will also be some Latex issues with memTrack, it’ll fail looking for `man.sty`.  Just ctrl-C/ctrl-D to get out of the prompt and then `make` again; it should succeed on the second try.

To build the “common” project with no VxWorks, rename the makefiles:

```sh
cd common
find . -name Makefile.Vx -exec mv {} {}_no \;
```


## mcba_usb

At JCMT, Namakanui uses a USB Microchip CANBus Analyzer to interface with the FEMC.  An open-source Linux SocketCAN driver, along with a firmware update that should be applied to the device, can be found here:

<https://github.com/rkollataj/mcba_usb>

On gltcanbus, a service is in place to start the `can0` network interface.  You can find the config file at `/etc/systemd/system/canbus.service`.



