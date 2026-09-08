# stats-cli

Small dependency-free Python CLI for calculating the minimum, maximum, sum,
and average of numbers. It also reports the number of values supplied.

## Usage

```sh
python3 stats_cli.py 2 4 6
```

The project can also be packaged as a standalone zipapp:

```sh
python3 -m zipapp stats-cli -m 'stats_cli:main' -o stats-cli.pyz
python3 stats-cli.pyz 2 4 6
```

Invalid or empty input exits with status 2 and an error message. Tests use
only Python's standard-library `unittest` module:

```sh
python3 -m unittest -v
```
