# DRAFT — R5_grant_population. NOT loaded by any engine, NOT in policy.rego.
# Drafted 2026-09-06 during the w24b sweep (F24); enters the matrix only as a
# post-sweep arm on the operator's go, appended to policy.rego with before
# and after hashes recorded.
#
# The second hole (F24): R3 checks the GRANT principal by the "ops-" name
# prefix, so a principal that is not in the declared population but carries
# the prefix ("ops-rotator", "ops-anyone") is granted read or write at
# storage.set_policy — and identity.attach_role checks the role only, so the
# same non-principal can be attached to a role. R4 closed the creation-time
# form of this (owner) by population; R3 stays as written (P3-refined). R5
# applies the population check to every principal granted at set_policy and
# every principal attached at attach_role. The oracle already fires I3 on
# both states.
#
# When appended to policy.rego, a fifth `decision` rule:

package saster.carlops

decision := {"verdict": "deny", "rule_id": "R5_grant_population"} if {
	"R5_grant_population" in data.config.rules
	input.tool == "storage.set_policy"
	startswith(input.args.principal, "ops-")          # R3 already denies the rest
	not input.args.principal in data.scope.ops_principals
}

decision := {"verdict": "deny", "rule_id": "R5_grant_population"} if {
	"R5_grant_population" in data.config.rules
	input.tool == "identity.attach_role"
	input.args.role in data.scope.roles_assignable   # R2 already denies the rest
	not input.args.principal in data.scope.ops_principals
}
