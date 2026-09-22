# Scope, licenses and exclusions

This notice inventories the bounded sharing set; it does not establish a new
project-wide license or claim that every future full-corpus dependency has been
cleared for distribution.

| Material | Source and notice | Treatment |
|---|---|---|
| MVC Music Store legacy source, reproduced excerpts/catalog material and derivative generated application source | `chack411/MVC-Music-Store` commit `2967afb9d69488641df0d154e2ad5827a7820e71`; the original `readme.txt` identifies Microsoft Public License (Ms-PL) | Original attribution/readme retained; full `LICENSES/MS-PL.txt` included. Ms-PL applies to reproduced source and derivative portions. |
| OpenCode system prompt and tool descriptions recorded in provider requests | OpenCode 1.17.11, copyright (c) 2025 opencode, MIT | Full upstream `LICENSES/OpenCode-MIT.txt` included for reproduced portions. |
| Tutorial PDF | Upstream readme identifies Creative Commons Attribution 3.0 | PDF excluded. No tutorial-document reproduction is claimed. |
| Legacy script/image/database packages, .NET/NuGet native and managed binaries, evaluator bundle, browser/worker images | Separate component terms have not been fully inventoried for this rehearsal | Omitted. Pin references remain; this prevents a self-contained environment replay. |
| Playwright trace containers, screenshots, HTTP logs and evaluator output | Output of the frozen local research workflow; trace resources inspected as generated local HTML/CSS, synthetic responses and viewport images | Retained, with local-home-path replacements in trace text. No Playwright/browser executables are included. |
| sample2-authored readers and research records | `fukuda-yuki/sample2`; no repository-wide license file was found at the base revision | Existing status retained. Public availability alone is not a new broad reuse license. An explicit data/tool license remains a separate owner decision. |

The license text sources are:

- [MS-PL at SPDX](https://github.com/spdx/license-list-data/blob/main/text/MS-PL.txt), checked against the [OSI text](https://opensource.org/license/ms-pl).
- [OpenCode 1.17.11 MIT license](https://github.com/anomalyco/opencode/blob/v1.17.11/LICENSE).

The gateway DBs contain usage/trace metadata, not a complete conversation or
unobserved internal reasoning. Provider request/response and native event files
are supplied separately. Synthetic Music Store names, catalog entries, test
email addresses and localhost cart/session identifiers are part of the workload.
Saved browser logs also include failed `local.adguard.org` extension requests;
these are retained observations, not a reason to alter the recorded verdicts.

`MANIFEST.json` enumerates exclusions and redactions at file level. Native agent
state/auth caches and evaluation DB/WALs are omitted from this demonstration.
Request/response bytes, available agent events and recorded evaluator evidence
support the stated offline extraction; excluded native-state, DB-query and full
environment replay capabilities must not be reported as reproduced.
