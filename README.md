# Electrum-GLC - Lightweight Goldcoin client

```
Licence: MIT Licence
Author: Thomas Voegtlin
Port Maintainer: expatjedi
Language: Python (>= 3.8)
Homepage: https://https://www.goldcoinproject.org/
```


## Getting started

_(If you've come here looking to simply run Electrum-LTC,
[you may download it here](https://www.goldcoinproject.org/downloads.html).)_

Electrum-GLC itself is pure Python, and so are most of the required dependencies,
but not everything. The following sections describe how to run from source, but here
is a TL;DR:

```
$ sudo apt install libsecp256k1-0
$ python3 -m pip install --user ".[gui,crypto]"
```

### Not pure-python dependencies

If you want to use the Qt interface, install the Qt dependencies:
```
$ sudo apt install python3-pyqt5
```

For elliptic curve operations,
[libsecp256k1](https://github.com/bitcoin-core/secp256k1)
is a required dependency:
```
$ sudo apt install libsecp256k1-0
```

Alternatively, when running from a cloned repository, a script is provided to build
libsecp256k1 yourself:
```
$ sudo apt install automake libtool
$ ./contrib/make_libsecp256k1.sh
```

Due to the need for fast symmetric ciphers,
[cryptography](https://github.com/pyca/cryptography) is required.
Install from your package manager (or from pip):
```
$ sudo apt install python3-cryptography
```

For fast blockchain verification,
[scrypt](https://github.com/holgern/py-scrypt) is required.
Install from your package manager (or from pip):
```
$ sudo apt install python3-scrypt
```

If you would like hardware wallet support,
[see this](https://github.com/spesmilo/electrum-docs/blob/master/hardware-linux.rst).


### Running from tar.gz

If you downloaded the official package (tar.gz), you can run
Electrum-GLC from its root directory without installing it on your
system; all the pure python dependencies are included in the 'packages'
directory. To run Electrum-GLC from its root directory, just do:
```
$ ./run_electrum
```

You can also install Electrum-GLC on your system, by running this command:
```
$ sudo apt install python3-setuptools python3-pip
$ python3 -m pip install --user .
```

This will download and install the Python dependencies used by
Electrum-GLC instead of using the 'packages' directory.
It will also place an executable named `electrum-glc` in `~/.local/bin`,
so make sure that is on your `PATH` variable.


### Development version (git clone)

_(For OS-specific instructions, see [here for Windows](contrib/build-wine/README_windows.md),
and [for macOS](contrib/osx/README_macos.md))_

Check out the code from GitHub:
```
$ git clone https://github.com/goldcoin/electrum-glc.git
$ cd electrum-glc
$ git submodule update --init
```

Run install (this should install dependencies):
```
$ python3 -m pip install --user -e .
```

Create translations (optional):
```
$ sudo apt install python-requests gettext
$ ./contrib/pull_locale
```

Finally, to start Electrum-GLC:
```
$ ./run_electrum
```

### Run tests

Run unit tests with `pytest`:
```
$ pytest electrum_glc/tests -v
```

To run a single file, specify it directly like this:
```
$ pytest electrum_glc/tests/test_bitcoin.py -v
```

## Creating Binaries

- [Linux (tarball)](contrib/build-linux/sdist/README.md)
- [Linux (AppImage)](contrib/build-linux/appimage/README.md)
- [macOS](contrib/osx/README.md)
- [Windows](contrib/build-wine/README.md)
- [Android](contrib/android/Readme.md)


## Contributing

Any help testing the software, reporting or fixing bugs, reviewing pull requests
and recent changes, writing tests, or helping with outstanding issues is very welcome.
Implementing new features, or improving/refactoring the codebase, is of course
also welcome, but to avoid wasted effort, especially for larger changes,
we encourage discussing these on the issue tracker or discord first.

Besides [GitHub](https://github.com/goldcoin/electrum-glc),
most communication about Electrum-GLC development happens on discord.
The easiest way to participate, click here [discord server](https://discord.me/goldcoin).
