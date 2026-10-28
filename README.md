# AI Solution Builder

AI Solution Builder (ASB) is a platform-neutral module-builder: a Python CLI (`asb`) and a Claude plugin that turn a business description into an approved model, then generate, verify and operate the resulting module. The core stays free of any ERP, framework or pack; those live in `packs/` and `connectors/` and are loaded through their YAML descriptors.

See `docs/` for the design spec and implementation plan.
