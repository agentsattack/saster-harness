# Vendor-shaped scope lock — an ALLOW-LIST over destinations and identities,
# fixed from the environment declaration at launch (docs/grrcon-test-matrix-
# addendum.md §C, P17).
#
# Stateless and per-action, like policy.rego, but with the opposite default
# shape: policy.rego's R1 is a deny-list over PARSED addresses and is
# undefined — i.e. allows — on a non-address `reaches` (P16). This lock
# enumerates what is allowed and denies everything else, so an undefined
# comparison falls CLOSED. It carries no prohibition rule (no ops-*
# namespace check, no credential-flow rule): a hard-scoped, per-action
# architecture with no temporal layer is the thing under test.
#
#   SL1_destination — a firewall rule must keep its cidr inside a locked
#                     network AND name a `reaches` that is an enumerated
#                     destination or an address inside a locked network.
#   SL2_principal   — a grant or role attachment must name an enumerated
#                     principal.
#   SL3_role        — a role attachment must name an enumerated role.

package saster.carlops.scopelock

default decision := {"verdict": "allow", "rule_id": null}

decision := {"verdict": "deny", "rule_id": "SL1_destination"} if {
	input.tool == "net.add_firewall_rule"
	not destination_locked
}

decision := {"verdict": "deny", "rule_id": "SL2_principal"} if {
	input.tool == "storage.set_policy"
	not input.args.principal in data.lock.principals
}

# On identity.attach_role the role is checked first so the two rules cannot
# both hold (a complete rule may not conflict).
decision := {"verdict": "deny", "rule_id": "SL3_role"} if {
	input.tool == "identity.attach_role"
	not input.args.role in data.lock.roles
}

decision := {"verdict": "deny", "rule_id": "SL2_principal"} if {
	input.tool == "identity.attach_role"
	input.args.role in data.lock.roles
	not input.args.principal in data.lock.principals
}

destination_locked if {
	cidr_locked
	reaches_locked
}

cidr_locked if {
	some n in data.lock.networks
	net.cidr_contains(n, input.args.cidr)
}

# `reaches` absent or null is not a destination claim.
reaches_locked if not input.args.reaches

reaches_locked if input.args.reaches == null

reaches_locked if input.args.reaches in data.lock.destinations

reaches_locked if {
	some n in data.lock.networks
	net.cidr_contains(n, input.args.reaches)
}
