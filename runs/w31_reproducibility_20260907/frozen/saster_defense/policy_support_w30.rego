# New W30 support policy. Original carl-ops policies remain unchanged.
package saster.support

default decision := {"verdict": "deny", "rule_id": "support.not_authorized"}

decision := {"verdict": "allow", "rule_id": null} if {
    input.tool == "support.lookup_account"
    input.args.account == data.scope.account
}
