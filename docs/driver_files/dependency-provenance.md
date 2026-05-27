# Dependency Provenance

This page records the direct runtime dependencies declared in `pyproject.toml`, including optional extras and
excluding the `dev` dependency group.

It is not a security rating. The goal is narrower: document, as far as we can tell from public project metadata,
which real-world people, teams, companies, or institutions appear to stand behind each dependency.

Classifications used here:

- `individual-led`: primarily associated with one named person, even if others also contribute
- `small team`: maintained by a small named maintainer group
- `community team`: maintained by a multi-person open source team without a single obvious vendor owner
- `institution-backed`: explicitly tied to a named institution, foundation, or authority
- `institution-originated individual-led`: originated in an institutional or research setting but appears primarily led by one named individual

## Direct Runtime Dependencies

### `tomli`

- Selected by: base dependency on Python < 3.11
- Classification: `small team`
- Maintainer signal: PyPI lists author Taneli Hukkinen and maintainers `encukou`, `hauntsaninja`, and `hukkin`.[^tomli-pypi]

### `python-gitlab`

- Selected by: `gitlab`, `all`
- Classification: `community team`
- Maintainer signal: PyPI lists author Gauvain Pocentek, maintainer John Villalovos, and maintainers `bufferoverflow`, `max-wittig`, and `nejch`.[^python-gitlab-pypi]

### `pywin32`

- Selected by: `weak-sandbox`
- Classification: `small team`
- Maintainer signal: PyPI lists author Mark Hammond et al. and maintainers `glyph`, `mhammond`, and `pf_moore`.[^pywin32-pypi]

### `orjson`

- Selected by: `fast`, `all`
- Classification: `individual-led`
- Maintainer signal: PyPI lists maintainer `ijl`.[^orjson-pypi]

### `rtoml`

- Selected by: `fast`, `all`
- Classification: `individual-led`
- Maintainer signal: PyPI lists author Samuel Colvin and maintainer `samuelcolvin`.[^rtoml-pypi]

### `bagit`

- Selected by: `antitamper`, `all`
- Classification: `institution-backed`
- Maintainer signal: PyPI lists author Ed Summers, maintainers `acdha` and `esummers`, and a project homepage under the Library of Congress.[^bagit-sources]

### `prompt-toolkit`

- Selected by: `prompt-toolkit`
- Classification: `individual-led`
- Maintainer signal: PyPI lists author Jonathan Slenders and maintainer `jonathan.slenders`.[^prompt-toolkit-pypi]

### `pip-audit`

- Selected by: `selfcheck`, `all`
- Classification: `institution-backed`
- Maintainer signal: PyPI lists owner Python Packaging Authority, author Alex Cameron, and maintainers `di`, `trailofbits`, and `woodruffw`.[^pip-audit-pypi]

### `mini-racer`

- Selected by: `js-miniracer`, `code-interpreters`, `all`
- Classification: `individual-led`
- Maintainer signal: PyPI lists author `bpcreech` and maintainer `bpcreech`.[^mini-racer-pypi]

### `dukpy`

- Selected by: `js-dukpy`, `code-interpreters`, `all`
- Classification: `individual-led`
- Maintainer signal: PyPI lists author Alessandro Molina and maintainer `amol`.[^dukpy-pypi]

### `lupa`

- Selected by: `lua`, `code-interpreters`, `all`
- Classification: `individual-led`
- Maintainer signal: PyPI lists author Stefan Behnel, maintainer `scoder`, and a project maintainer field of `Lupa-dev mailing list`.[^lupa-pypi]

### `html2text`

- Selected by: `web`
- Classification: `small team`
- Maintainer signal: PyPI lists author Aaron Swartz, maintainer Alireza Savand, and maintainers `Alir3z4` and `jdufresne`.[^html2text-pypi]

### `readability-lxml`

- Selected by: `web`
- Classification: `small team`
- Maintainer signal: PyPI lists author Yuri Baburov and maintainers `mitechie` and `Yuri.Baburov`.[^readability-lxml-pypi]

### `trafilatura`

- Selected by: `web`
- Classification: `institution-originated individual-led`
- Maintainer signal: PyPI lists author and maintainer `adbar` / Adrien Barbaresi, and the project description says the work started as a PhD project tied to research units at the Berlin-Brandenburg Academy of Sciences.[^trafilatura-pypi]

## Notes

- This page covers only direct dependencies declared by this project. It does not yet cover transitive dependencies.
- Optional dependency aliases such as `js-miniracer`, `js-dukpy`, `lua`, and `code-interpreters` ultimately point to the same deduplicated package rows above.
- These classifications are descriptive shortcuts based on public metadata. They should not be read as a quality judgment.

## Sources

\[^tomli-pypi\]: [PyPI: `tomli`](https://pypi.org/project/tomli/)
\[^python-gitlab-pypi\]: [PyPI: `python-gitlab`](https://pypi.org/project/python-gitlab/)
\[^pywin32-pypi\]: [PyPI: `pywin32`](https://pypi.org/project/pywin32/)
\[^orjson-pypi\]: [PyPI: `orjson`](https://pypi.org/project/orjson/)
\[^rtoml-pypi\]: [PyPI: `rtoml`](https://pypi.org/project/rtoml/)
\[^bagit-sources\]: Sources: [PyPI: `bagit`](https://pypi.org/project/bagit/); [Library of Congress: `bagit-python`](https://libraryofcongress.github.io/bagit-python/)
\[^prompt-toolkit-pypi\]: [PyPI: `prompt-toolkit`](https://pypi.org/project/prompt-toolkit/)
\[^pip-audit-pypi\]: [PyPI: `pip-audit`](https://pypi.org/project/pip-audit/)
\[^mini-racer-pypi\]: [PyPI: `mini-racer`](https://pypi.org/project/mini-racer/)
\[^dukpy-pypi\]: [PyPI: `dukpy`](https://pypi.org/project/dukpy/)
\[^lupa-pypi\]: [PyPI: `lupa`](https://pypi.org/project/lupa/)
\[^html2text-pypi\]: [PyPI: `html2text`](https://pypi.org/project/html2text/)
\[^readability-lxml-pypi\]: [PyPI: `readability-lxml`](https://pypi.org/project/readability-lxml/)
\[^trafilatura-pypi\]: [PyPI: `trafilatura`](https://pypi.org/project/trafilatura/)
