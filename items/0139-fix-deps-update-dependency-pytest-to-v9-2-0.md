# #139 fix(deps): update dependency pytest to v9.2.0

- Kind: pull, state: closed, by renovate, created 2026-10-27T15:08:47-07:00
- Labels: none; milestone: none
- refs/pull/139/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [pytest](https://github.com/pytest-dev/pytest) ([changelog](https://docs.pytest.org/en/stable/changelog.html)) | `==9.1.1` → `==9.2.0` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/pytest/9.2.0?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/pytest/9.1.1/9.2.0?slim=true) |

---

### Release Notes

<details>
<summary>pytest-dev/pytest (pytest)</summary>

### [`v9.2.0`](https://github.com/pytest-dev/pytest/releases/tag/9.2.0)

[Compare Source](https://github.com/pytest-dev/pytest/compare/9.1.1...9.2.0)

### pytest 9.2.0 (2026-10-27)

#### Removals and backward incompatible breaking changes

- [#&#8203;14716](https://github.com/pytest-dev/pytest/issues/14716): `-c` now raises a usage error for a path that does not exist, is a directory, or is in a format pytest has no loader for. Such paths were previously either ignored or reported as an unhandled `FileNotFoundError`.

- [#&#8203;8593](https://github.com/pytest-dev/pytest/issues/8593): The `indirect`, `ids` and `scope` arguments of `Metafunc.parametrize() <pytest.Metafunc.parametrize>` -- and therefore of `@pytest.mark.parametrize <pytest.mark.parametrize ref>` -- are now keyword-only.

  Passing them positionally was a common source of confusing errors, e.g. `parametrize("arg1", "arg2", [(1, 2)])` made the argvalues land in `indirect` and failed with `indirect fixture '(1, 2)' doesn't exist`; such mistakes now fail with an understandable `TypeError`. The type annotations have always declared these arguments as keyword-only.

- [#&#8203;993](https://github.com/pytest-dev/pytest/issues/993): Plugin import failures at startup are now reported and classified instead of escaping as a raw traceback with the accidental exit code `1`:

  - a plugin that cannot be found -- via `-p`, `pytest_plugins` or `PYTEST_PLUGINS` -- exits with `pytest.ExitCode` `USAGE_ERROR` (`4`), like a `conftest.py` that fails to import;
  - a plugin that is found but raises while importing -- including a broken `pytest11` entry point or a missing plugin dependency -- exits with `pytest.ExitCode` `INTERNAL_ERROR` (`3`), with the traceback preserved.

  `pytest.main` now returns these codes instead of raising `ImportError`. Also fixed an `IndexError` from pytest's own internals when the plugin raised an exception with no arguments.

#### Deprecations (removal in next major release)

- [#&#8203;14742](https://github.com/pytest-dev/pytest/issues/14742): The private `_pytest.python.CallSpec2` name has been renamed to `CallSpec`.
  The old `CallSpec2` alias remains available for now and will be removed in pytest 10 or 11.

- [#&#8203;14755](https://github.com/pytest-dev/pytest/issues/14755): Schedule *yield_fixture* decorator for removal in pytest 10 or 11.

- [#&#8203;14774](https://github.com/pytest-dev/pytest/issues/14774): Similarly to the deprecation of class-scoped fixtures defined as instance methods in pytest 9.1,
  *all* higher-scoped fixtures (`module`, `package`, and `session`) defined
  as instance methods are now deprecated.

  They suffer from the same issue the original deprecation only fixed for
  class-scoped fixtures, see `10819` and `14011`.

- [#&#8203;14808](https://github.com/pytest-dev/pytest/issues/14808): Passing a non-string value to a `string`-typed ini option now emits a `pytest.PytestRemovedIn10Warning`. This affects `[tool.pytest.ini_options]` in `pyproject.toml`. In pytest 10 this will raise a `TypeError`, matching the behavior of the corresponding TOML config path.

- [#&#8203;7323](https://github.com/pytest-dev/pytest/issues/7323): Passing `bytes` to `TerminalReporter.write_line()` is now deprecated, pass a `str` instead.

#### New features

- [#&#8203;14743](https://github.com/pytest-dev/pytest/issues/14743): <span class="title-ref">Full diff:</span> now contains a legend explaining the <span class="title-ref">+</span> & <span class="title-ref">-</span> symbols in diff output.
- [#&#8203;2781](https://github.com/pytest-dev/pytest/issues/2781): When `strict_markers` is enabled, marker names used in `-m` expressions are now validated against registered markers.
- [#&#8203;6881](https://github.com/pytest-dev/pytest/issues/6881): Added the `parametrize_long_str_id_strategy` configuration option to control how long `str`/`bytes` parameter values are handled in auto-generated test IDs. Explicit IDs set via `ids=[...]` or `pytest.param(..., id=...)` are not affected. Available strategies: `short` (default, values over 100 chars fall back to `argname+index`), `sha256` (SHA-256 hex digest), `legacy` (keep full value), and `disallow` (error requesting explicit IDs).

#### Improvements in existing functionality

- [#&#8203;10745](https://github.com/pytest-dev/pytest/issues/10745): A `RecursionError` whose recursion origin cannot be located now shows only the
  first and last 10 stack frames, matching what pytest already did when locating
  the origin failed outright. Previously the full traceback -- often around a
  thousand near-identical frames -- was rendered, which was both slow and
  unreadable. Pass `--full-trace` to see every frame.

- [#&#8203;10745](https://github.com/pytest-dev/pytest/issues/10745): The line numbers of a module's statements are now computed once per traceback
  instead of once per traceback entry, which noticeably speeds up rendering
  failures raised from large test modules.

- [#&#8203;11418](https://github.com/pytest-dev/pytest/issues/11418): The cached rewritten modules in `__pycache__` are now invalidated by a hash of
  the source instead of its modification time, using the checked-hash pyc format
  from `552`.

  Timestamps make the cache useless wherever source files get fresh modification
  times, most notably in CI: a checkout gives every file a new mtime, so a
  restored cache is discarded in full and every test module is rewritten again.
  Hashing the source costs roughly 15 microseconds per file and makes the cache
  survive that.

  Existing timestamp based caches are ignored and rewritten once.

- [#&#8203;12624](https://github.com/pytest-dev/pytest/issues/12624): The `pytest_plugins` variable and the `PYTEST_PLUGINS` environment variable now also accept entry point names of installed plugins (e.g. `xdist`), in addition to importable module names, matching the behavior of the `-p` command-line option.

  As part of this change, plugins specified by entry point name through these mechanisms are now also listed in the `plugins:` line of the terminal header (`12615`).

  Based on the original implementation by Marcel Telka in `12616`.

- [#&#8203;12697](https://github.com/pytest-dev/pytest/issues/12697): Warnings emitted while importing plugins through `-p`, `PYTEST_PLUGINS`, or entry point autoloading are now captured, filtered, and reported like other warnings.

- [#&#8203;12860](https://github.com/pytest-dev/pytest/issues/12860): Assertion diffs for `dict.items()` and `dict.keys()` comparisons (`>=`, `<=`, `>`, `<`, `==`) now show which items are missing, the same way set comparisons do.

- [#&#8203;13354](https://github.com/pytest-dev/pytest/issues/13354): `Node.get_closest_marker <_pytest.nodes.Node.get_closest_marker>` now also accepts a `~pytest.MarkDecorator` as its `default`, for example `item.get_closest_marker("foo", pytest.mark.foo(1))`, and returns the wrapped `~pytest.Mark`.

  Previously the only way to build a `default` was to instantiate `~pytest.Mark` directly, which is private and warns.

- [#&#8203;13369](https://github.com/pytest-dev/pytest/issues/13369): Improved the error from `pytest.RunResult.assert_outcomes` when a plugin changes or removes pytest's standard terminal summary, and documented how to isolate output-changing plugins.

- [#&#8203;13431](https://github.com/pytest-dev/pytest/issues/13431): Exposed `pytest.ParameterSet` as the type of the return value of `pytest.param()`.
  This can be used in type annotations and `isinstance` checks.

- [#&#8203;13564](https://github.com/pytest-dev/pytest/issues/13564): Issue a warning when fixtures are wrapped with a decorator that prevents
  correct discovery, including `@classmethod` above `@pytest.fixture` and
  `@staticmethod` above `@pytest.fixture`. Put `@pytest.fixture` above
  those decorators on test classes.

- [#&#8203;14164](https://github.com/pytest-dev/pytest/issues/14164): Exposed `pytest.Approx` as the type of the return value of `pytest.approx()`.
  This can be used in type annotations and `isinstance` checks.

- [#&#8203;14463](https://github.com/pytest-dev/pytest/issues/14463): Assertion diffs for mappings now match up keys the way the compared mappings match them themselves.

  Key comparison goes through the mappings' key views instead of plain sets of their keys, so a mapping
  with its own notion of key equivalence, such as case-insensitive header mappings, no longer
  reports its common keys as missing on either side.

- [#&#8203;14523](https://github.com/pytest-dev/pytest/issues/14523): Large assertion comparison diffs are now built lazily and capped to the
  truncation budget, so a huge diff is no longer formatted in full just to
  be truncated. As a consequence, the truncation footer no longer
  reports the exact number of hidden lines.

- [#&#8203;14687](https://github.com/pytest-dev/pytest/issues/14687): The default fd-level output capturing (`--capture=fd`) now skips reading the capture buffer for tests which produce no output, reducing per-test overhead in large test suites.

- [#&#8203;14724](https://github.com/pytest-dev/pytest/issues/14724): `--no-summary` now only applies directly to pytest's own summary.

  The flag no longer skips the `pytest_terminal_summary` hook, so third-party
  plugins (for example coverage) can still write their terminal summaries.

- [#&#8203;14751](https://github.com/pytest-dev/pytest/issues/14751): `parser.addini <pytest.Parser.addini>` now also accepts type expressions for its `type` argument, in addition to the existing string tags: the plain Python types `str`, `bool`, `int`, `float`, a `Literal` of strings, and unions of these (for example `int | str` or `int | Literal["auto"]`).

- [#&#8203;14754](https://github.com/pytest-dev/pytest/issues/14754): `pytest.approx()` now rejects infinite relative tolerances for `datetime.timedelta` values with a clear `ValueError` instead of raising `OverflowError`.

- [#&#8203;14791](https://github.com/pytest-dev/pytest/issues/14791): The `junit_family`, `junit_logging`, `junit_duration_report`, `console_output_style`, `empty_parameter_set_mark`, `assertion_text_diff_style` and `tmp_path_retention_policy` configuration options are now registered with the set of values they accept: an invalid value now fails with a clean usage error instead of being silently ignored or crashing later, and `pytest --help` lists the accepted values.

  `config.getini <pytest.Config.getini>` now raises `pytest.UsageError` instead of `TypeError` or `ValueError` when the value read from the configuration file does not match the registered type, so a bad value is always reported as a short usage error message instead of an internal error traceback. Asking for an option name that was never registered still raises `ValueError`.

- [#&#8203;15006](https://github.com/pytest-dev/pytest/issues/15006): `pytest.approx` now emits `pytest.PytestApproxDecimalToleranceWarning` when a `rel` or `abs` tolerance is given as a `float` that cannot be represented exactly for a `~decimal.Decimal` comparison, since such a tolerance is widened to the float's exact binary value.

- [#&#8203;14675](https://github.com/pytest-dev/pytest/issues/14675), [#&#8203;14953](https://github.com/pytest-dev/pytest/issues/14953), [#&#8203;15153](https://github.com/pytest-dev/pytest/issues/15153), [#&#8203;15132](https://github.com/pytest-dev/pytest/issues/15132): The `truncation_limit_lines`, `truncation_limit_chars`, `max_warnings`, `verbosity_assertions`, `verbosity_test_cases`, `verbosity_subtests`, `tmp_path_retention_count`, `log_level`, `log_cli_level`, `log_file_level`,`log_auto_indent` and `faulthandler_timeout` configuration options now accept native integer (and, for `log_auto_indent`, boolean) values in TOML configuration files, while still accepting strings for backward compatibility.
  `log_file_mode` now reports invalid values as a usage error.

- [#&#8203;15254](https://github.com/pytest-dev/pytest/issues/15254): `tmp_path` and `TempPathFactory.mktemp <pytest.TempPathFactory.mktemp>` no longer list the whole base temporary directory on every call, which made sessions with many temporary directories quadratically slow. Numbers are now handed out from a per-prefix counter, skipping names that already exist.

- [#&#8203;4569](https://github.com/pytest-dev/pytest/issues/4569): `Node.add_marker <_pytest.nodes.Node.add_marker>` now stores a `~pytest.Mark` in `node.keywords`, matching what marks applied during collection store. Previously it stored a `~pytest.MarkDecorator`.

- [#&#8203;9436](https://github.com/pytest-dev/pytest/issues/9436): Avoided formatting tracebacks for tests marked with `xfail(run=False)`.

#### Bug fixes

- [#&#8203;10128](https://github.com/pytest-dev/pytest/issues/10128): Configured warning filters now apply to warnings emitted by `pytest_configure` hooks.

- [#&#8203;10210](https://github.com/pytest-dev/pytest/issues/10210): `pytest.approx` now raises a `TypeError` for any nested container, not
  only for one of the same type as its parent. Previously `approx([{"k": 1}])`
  and `approx({"k": [1]})` were accepted and then compared unequal to every
  value, silently ignoring the tolerance, while `approx([[1]])` correctly
  reported that nesting is unsupported.

- [#&#8203;10644](https://github.com/pytest-dev/pytest/issues/10644): `monkeypatch.setattr()` no longer leaves a new entry in the instance `__dict__` when it patches an attribute that the instance inherits from its class.

  Previously `undo()` assigned the inherited value onto the instance, which shadowed the class attribute -- permanently freezing the result for descriptors that resolve dynamically.

- [#&#8203;1139](https://github.com/pytest-dev/pytest/issues/1139): Fixed tracebacks showing `???` instead of source lines for code compiled with a filename relative to a directory other than the current working directory -- e.g. compiled Cython modules, when running pytest from a subdirectory of the project root.
  The source lookup now falls back to searching `sys.path` for such filenames, as the standard `traceback` module does.

- [#&#8203;11502](https://github.com/pytest-dev/pytest/issues/11502): The `rootdir` is no longer derived from a configuration file that is not a regular file, such as `--config-file=/dev/null`.

- [#&#8203;11783](https://github.com/pytest-dev/pytest/issues/11783): Plugins installed in editable mode (`660`) are marked for assertion rewriting again.

  Such installs do not record the package's Python files in the distribution metadata, so pytest found nothing to rewrite and assertions inside the plugin lost their introspection. The plugin's entry point is now used to locate the package in that case.

- [#&#8203;11933](https://github.com/pytest-dev/pytest/issues/11933): `pytest.warns` no longer re-emits unmatched warnings with `module="warnings"`, which caused `module`-based warning filters to be applied to the wrong warnings. Since `warnings.WarningMessage` does not record the module a warning was emitted with, re-emitted warnings now use the standard `warnings.warn_explicit` default of deriving the module from the warning's filename.

- [#&#8203;12175](https://github.com/pytest-dev/pytest/issues/12175): `ExceptionInfo.exconly(tryshort=True) <pytest.ExceptionInfo.exconly>` now strips the `AssertionError:` prefix of failed `assert` statements for `~pytest.ExceptionInfo` objects created by `pytest.raises`, and failures inside `unittest.TestCase.subTest` report the same short crash line as regular tests.

- [#&#8203;12223](https://github.com/pytest-dev/pytest/issues/12223): The `message` attribute of `<failure>` and `<error>` elements in `--junitxml` reports is now shortened to whole lines within 500 characters. When something is dropped, it ends with a note pointing to the element text, which still holds the full report. Previously, very verbose assertion output (e.g. with `-vv`) produced attributes tens of thousands of characters long, which some XML parsers fail on.

- [#&#8203;12307](https://github.com/pytest-dev/pytest/issues/12307): Fixed truncation of long collections (lists, dicts, sets, etc.) in the "message" part of failed assertions (as in `assert condition, msg`) when using `-vv`: the message now uses the same unlimited repr as the rest of the assertion output, instead of eliding collection elements with `...`.

- [#&#8203;12824](https://github.com/pytest-dev/pytest/issues/12824): Custom command-line options now fail with a clear error when their implicit
  destination conflicts with an existing option, avoiding silent overrides of
  built-in options such as `-k`.

- [#&#8203;13292](https://github.com/pytest-dev/pytest/issues/13292): Fixed a stale rewritten module being used when a test file is modified twice
  within the same second without changing its size -- the pyc header could only
  record whole-second timestamps. The cache is now keyed on a hash of the source.

- [#&#8203;14036](https://github.com/pytest-dev/pytest/issues/14036): `__tracebackhide__` is now respected in `ExceptionGroup` tracebacks, both for the group itself and for its sub-exceptions.

- [#&#8203;14189](https://github.com/pytest-dev/pytest/issues/14189): Nested usage of `caplog.filtering <pytest.LogCaptureFixture.filtering>` no longer removes filters early if they were already present.

- [#&#8203;14412](https://github.com/pytest-dev/pytest/issues/14412): Fixed incorrect timing information for subtests and parent tests when `console_output_style = "times"`.

- [#&#8203;14445](https://github.com/pytest-dev/pytest/issues/14445): Assertion rewriting no longer evaluates walrus operator (`:=`) expressions more than once, which reported results the test never computed when the expression had side effects.

  An operand evaluated before a later walrus is now reported with the value it actually saw, so `assert value != identity(value := value.lower())` keeps Python's left-to-right order.

- [#&#8203;14552](https://github.com/pytest-dev/pytest/issues/14552): Fixed stale `co_filename` values after a test module or directory is moved. Assertion-rewrite caches are reused when the source hash still matches, and in-memory code objects are pointed at the current path.

- [#&#8203;14586](https://github.com/pytest-dev/pytest/issues/14586): Negative values passed to `log_auto_indent` now correctly fall back to no indentation, matching the documented behavior.

- [#&#8203;14619](https://github.com/pytest-dev/pytest/issues/14619): Fixed a crash in `pytest.mark.parametrize` when a non-sequence value is passed for a parameter set. It now provides a clear error message during collection.

- [#&#8203;14635](https://github.com/pytest-dev/pytest/issues/14635): Fixed fixture resolution failures when specifying multiple test paths on the command line that share common parent directories. Parametrized fixtures defined in a `conftest.py` could be silently dropped depending on the order of the specified paths.

- [#&#8203;14637](https://github.com/pytest-dev/pytest/issues/14637): Pytest now correctly skips identical trailing characters in assertion text diffs even when the compared strings differ at the beginning.

- [#&#8203;14638](https://github.com/pytest-dev/pytest/issues/14638): Top-level options in `pytest.toml` and `.pytest.toml` files now raise an error instead of being silently ignored when no `[pytest]` table is present.

- [#&#8203;14683](https://github.com/pytest-dev/pytest/issues/14683): Fixed a regression in pytest 9.1 where a conftest.py located in the rootdir was no longer visible to tests and doctests collected from *outside* the rootdir (for example when passing a parent directory of the rootdir as a collection argument, or setting `--rootdir` to a subdirectory).

  As a result, fixtures defined in such a conftest -- including `doctest_namespace` injections -- were not available, causing errors such as `NameError` in doctests.

- [#&#8203;14700](https://github.com/pytest-dev/pytest/issues/14700): Fixed an internal error on Python 3.12 when a doctest on a fixture-decorated function was skipped.

- [#&#8203;14705](https://github.com/pytest-dev/pytest/issues/14705): TOML configuration files passed via `-c` now also read their configuration from the `[pytest]` table, the one pytest's own configuration files use. The `[tool.pytest]` and `[tool.pytest.ini_options]` tables such files were previously restricted to keep working; using both styles in one file is an error.

- [#&#8203;14828](https://github.com/pytest-dev/pytest/issues/14828): Exception groups raised from another exception now print their cause chain only once in the traceback output.

- [#&#8203;14864](https://github.com/pytest-dev/pytest/issues/14864): Fixed collection on Windows collecting the whole suite instead of the given path, on file systems which do not support file IDs (`st_ino` is `0` for every file, as seen for example on `sshfs-win`/WinFsp mounts).

- [#&#8203;14884](https://github.com/pytest-dev/pytest/issues/14884): `Cache.get()`, `Cache.set()` and `Cache.mkdir()` now reject keys that resolve outside the cache directory, and `--cache-show` ignores glob matches outside it.

- [#&#8203;14909](https://github.com/pytest-dev/pytest/issues/14909): Fixed `MonkeyPatch.delattr <pytest.MonkeyPatch.delattr>`, `MonkeyPatch.setitem <pytest.MonkeyPatch.setitem>` and `MonkeyPatch.delitem <pytest.MonkeyPatch.delitem>` recording a stale undo entry when the underlying mutation failed, which could cause spurious errors during teardown. The undo entry is now recorded only after the mutation succeeds, matching the behavior of `MonkeyPatch.setattr <pytest.MonkeyPatch.setattr>`.

- [#&#8203;14912](https://github.com/pytest-dev/pytest/issues/14912): `~pytest.PytestWarning` instances defined in `_pytest.deprecated` are no longer reused across `warnings.warn` calls, so warnings raised as errors (e.g. with `-W error`) no longer accumulate stale traceback frames from previous raises.

- [#&#8203;14942](https://github.com/pytest-dev/pytest/issues/14942): Fixed a regression in 9.1.0 that made collection very slow (quadratic) when many fixtures are defined with the same name.
  This can happen particularly when many tests are defined in separate classes which inherit from a base class which defines fixtures (the fixtures are repeated per class).

- [#&#8203;15005](https://github.com/pytest-dev/pytest/issues/15005): `pytest.approx` no longer treats finite `~decimal.Decimal` values outside the `float` range (such as `Decimal("1e400")`) as infinite, which made in-tolerance comparisons fail.

- [#&#8203;15006](https://github.com/pytest-dev/pytest/issues/15006): Restored the tolerance shown by `pytest.approx` for `~decimal.Decimal` values, which since 9.0 displayed `???` for the default tolerance and reported the raw `rel` ratio instead of the absolute tolerance actually compared against.

- [#&#8203;15006](https://github.com/pytest-dev/pytest/issues/15006): The failure message for `pytest.approx` comparisons of `~decimal.Decimal` collections no longer reports `Max absolute difference: -inf`, or crashes for mappings, when the `decimal.FloatOperation` trap is set.

- [#&#8203;15006](https://github.com/pytest-dev/pytest/issues/15006): `pytest.approx` no longer raises `AttributeError` when comparing `numpy.ndarray` instances with `object` dtype, such as arrays of `~decimal.Decimal`.

- [#&#8203;15032](https://github.com/pytest-dev/pytest/issues/15032): Help texts for command-line options and configuration options now keep their indentation
  and blank lines. Previously each line was stripped before wrapping, so a wrapped
  list item was indistinguishable from a new one and blank lines were dropped; configuration
  option help lost its line breaks entirely.

- [#&#8203;15043](https://github.com/pytest-dev/pytest/issues/15043): Cache writes now emit `pytest.PytestCacheWarning` when writing or closing the cache file fails, consistent with errors opening the file.

- [#&#8203;15052](https://github.com/pytest-dev/pytest/issues/15052): Fixed possible off-by-one line numbers in `--fixtures` and `--fixtures-per-test` output.

- [#&#8203;15145](https://github.com/pytest-dev/pytest/issues/15145): With `console_output_style` set to `times`, durations just below a unit boundary are now shown in the next unit (e.g. `1.000ms` instead of `1000.0us`).

- [#&#8203;15172](https://github.com/pytest-dev/pytest/issues/15172): Assertion diffs now pretty-print the built-in `frozendict` (Python 3.15+) across multiple lines, similarly to how `dict` is displayed.

- [#&#8203;4569](https://github.com/pytest-dev/pytest/issues/4569): `-k` no longer matches attributes that end up in a test function's `__dict__` without being meant as keywords, such as pytest's own `pytestmark` attribute and the bookkeeping left behind by `functools.wraps` and `functools.lru_cache`.

- [#&#8203;6750](https://github.com/pytest-dev/pytest/issues/6750): Fix fixture argument discovery for custom collectors that pass bound methods to `pytest.Function`.

- [#&#8203;6997](https://github.com/pytest-dev/pytest/issues/6997): XFAIL reports from teardown phases now include the phase in the short test
  summary.

- [#&#8203;7940](https://github.com/pytest-dev/pytest/issues/7940): Fixed cleanup of temporary directories failing when subdirectories have their execute permission removed.

- [#&#8203;8321](https://github.com/pytest-dev/pytest/issues/8321): Fixed exception chains being duplicated in the traceback output when an exception in the chain (`__cause__`/`__context__`) has no traceback of its own, and that exception is itself linked to further exceptions.

- [#&#8203;8914](https://github.com/pytest-dev/pytest/issues/8914): Tests parametrized with higher-than-function scope are now reordered by
  parameter *value* rather than by parameter *index*, so that items using equal
  parameter values are grouped together and share a single fixture setup, even
  when they are parametrized by separate `@pytest.mark.parametrize <pytest.mark.parametrize ref>`
  calls. Previously, an expensive higher-scoped fixture could be set up and torn
  down repeatedly for the same parameter value.

  Unhashable parameter values (e.g. dicts) keep the previous index-based
  grouping behavior.

  As a consequence, the order in which parametrized tests run may change
  (fixture setup/teardown counts can only decrease, not increase).

- [#&#8203;9924](https://github.com/pytest-dev/pytest/issues/9924): Fixed doctest option flags leaking between docstrings after a failure, skip, or expected failure.

#### Improved documentation

- [#&#8203;10721](https://github.com/pytest-dev/pytest/issues/10721): Replaced `setup.py` usage with `pyproject.toml` in `writing-plugins`.
- [#&#8203;12658](https://github.com/pytest-dev/pytest/issues/12658): Moved the fixture setup and finalizer hooks to the test running hooks section in the reference documentation.
- [#&#8203;12857](https://github.com/pytest-dev/pytest/issues/12857): Documented how `--confcutdir` affects initial `conftest.py` discovery.
- [#&#8203;14157](https://github.com/pytest-dev/pytest/issues/14157): Added the `pytest-flakefighters` plugin to the list of flaky test plugins in `plugins.rst`.
  Added flaky test papers published on the [Test FLARE](https://test-flare.github.io/) project to the list of flaky papers in `plugins.rst`.
- [#&#8203;15127](https://github.com/pytest-dev/pytest/issues/15127): Added guidance on typing yield fixtures, including annotating fixture functions with their generator type and fixture consumers with the yielded value type.
- [#&#8203;15242](https://github.com/pytest-dev/pytest/issues/15242): The `installation instructions <installation>` and `install-package-with-pip` now show how to install pytest into a virtual environment with venv and pip, uv or virtualenv, and explain the `externally-managed-environment` error.
- [#&#8203;4569](https://github.com/pytest-dev/pytest/issues/4569): `pytest --help`, the `-k` reference entry and `select-tests` no longer describe `-k` as a Python expression matched against test names only; `keyword expressions` now shows marker names being matched as well. The examples that looked up a marker use `Node.get_closest_marker <_pytest.nodes.Node.get_closest_marker>` rather than `item.keywords`.
- [#&#8203;9614](https://github.com/pytest-dev/pytest/issues/9614): Clarified that `session.items` and `session.testscollected` exclude deselected tests in the `pytest_collection` documentation.

#### Packaging updates and notes for downstreams

- [#&#8203;11680](https://github.com/pytest-dev/pytest/issues/11680): Source archives of arbitrary commits -- the tarballs GitHub serves under
  `/archive/`, not just the ones for tags -- can now be built into an sdist or a
  wheel with a correct version. A `.git_archival.txt` file, expanded by `git archive` via `export-subst`, carries the describe output that
  `setuptools-scm` would otherwise have to ask `git` for.

  The archival file deliberately omits `ref-names`. Recording it would make the
  content of an archive -- and therefore its checksum -- change whenever a branch
  that points at the archived commit is moved afterwards, which is how the
  equivalent tarballs of tagged releases became unstable for other projects.
  Describe output alone depends only on the commit and on the tags reachable from
  it.

  The archival file is not shipped in the sdist -- an sdist carries its version
  in its metadata, and the template is only ever expanded by `git archive`.

  Building pytest from a git checkout now requires `setuptools-scm >= 10.1`.

- [#&#8203;9236](https://github.com/pytest-dev/pytest/issues/9236): `pluggy>=1.6` is now required.

  Older pluggy versions stopped running the remaining hook wrapper teardowns once an
  old-style `hookwrapper` raised in its own teardown. The logging plugin's wrapper was
  left suspended, and when it was finalised later it detached the handler that
  `caplog` of a subsequent test was recording through, so that test saw no records.

#### Contributor-facing changes

- [#&#8203;14813](https://github.com/pytest-dev/pytest/issues/14813): Added a systematic coverage matrix for assertion rewriting.
- [#&#8203;14921](https://github.com/pytest-dev/pytest/issues/14921): Added <span class="title-ref">scripts/diff-assert-rewrite.py</span>, which diffs the assert-rewritten form of a snippet between the plain source, this checkout and released pytest versions.
- [#&#8203;15190](https://github.com/pytest-dev/pytest/issues/15190): Fixed the documentation build with Pluggy 1.7 by ignoring a reference to its undocumented `DistFacade` compatibility class.

#### Miscellaneous internal changes

- [#&#8203;13888](https://github.com/pytest-dev/pytest/issues/13888): `FixtureRequest.node <pytest.FixtureRequest.node>` is now explicitly annotated as returning `Any`, so strict pyright no longer reports it as `Unknown`. The return type stays deliberately broad, see `13888`.
- [#&#8203;14758](https://github.com/pytest-dev/pytest/issues/14758): Internal node ids (the `::`-separated strings identifying collected items, e.g. `path/to/test_file.py::TestClass::test_method[param]`) are now represented internally by a single structured `~_pytest.nodeid.NodeId` dataclass instead of being repeatedly re-parsed as plain strings. The public `nodeid: str` attribute on nodes and reports is unchanged and remains fully backward compatible for plugins.

</details>

---

### Configuration

📅 **Schedule**: (UTC)

- Branch creation
  - At any time (no schedule defined)
- Automerge
  - At any time (no schedule defined)

🚦 **Automerge**: Enabled.

♻ **Rebasing**: Whenever PR is behind base branch, or you tick the rebase/retry checkbox.

🔕 **Ignore**: Close this PR and you won't be reminded about this update again.

---

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box

---

This PR has been generated by [Mend Renovate CLI](https://github.com/renovatebot/renovate).
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4xNTEuMiIsInVwZGF0ZWRJblZlciI6IjQ0LjE5Mi4wIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJtaW5vci11cGRhdGUiXX0=-->
