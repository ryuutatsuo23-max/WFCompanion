local _, ns = ...
-- Dependency loading is enforced by the TOC. Keep inventory state out of Core.
local core = WFCore
assert(type(core)=="table" and core.apiVersion==1,"Forever Storage requires compatible Forever Core (API 1)")
core.AttachNamespace(ns)
ns.version = "0.7.0"
WFStorage = ns
