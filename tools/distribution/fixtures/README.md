# Historical configuration test fixture

`addon_configuration_schema1.py` is the exact schema-1 configuration writer from
commit `b5557e32fd7b62a47d6b64ce31bf93a758c40855` of the original development source. It is included as
source, without importing that repository's unrelated Git history.

SHA-256: `7425e444bd8d54e96498e4336b96fae5510e12959bcc4a4d7e51e831e01ac84d`

The adoption regression checks this hash and runs the writer only against new
synthetic clients and temporary backup roots. Keeping the genuine writer catches
incompatibility with real schema-1 records; the test does not manufacture a legacy
record by removing identity fields from the current format.

This is a test dependency under the project's existing licence, not a supported
runtime API. It must never be collected in a companion bundle. The exact runtime
allowlist and packaging regression enforce that exclusion. There is no user data,
backup, generated installer or historical test output in this directory.
