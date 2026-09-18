# Design

The [specification](spec.md) is the living source of truth for what ss-common provides. It holds
the capability registry, the evaluation of each capability, its boundaries, and the process for
adding capabilities discovered during implementation. The registry order is the implementation
line followed by the [forward plan](../impl/plan.md); `make lint-spec-plan` makes disagreement a
build failure.
