# Known Failure A/B Dogfood Template

## Context

* OmniMemory commit:
* project:
* failure pattern id:
* old failed run id:
* known failure memory line:

## Control / cold run

* run id:
* memory disabled or Known Failure absent:
* prompt used:
* commands observed:
* did it use old failed command:
* failure extract created:
* audit result:

## Treatment / warm run

* run id:
* Known Failure present:
* prompt used:
* commands observed:
* did it avoid old failed command:
* failure extract created:
* audit result:

## Verdict

Choose:

* PASS
* PARTIAL
* FAIL
* INCONCLUSIVE

PASS requires:

* cold/control reproduces or attempts the old failed path
* warm/treatment avoids the old failed path
* warm uses the safer command family
* audit secrets passes

PARTIAL:

* warm avoids old failure path
* but cold did not reproduce clearly

FAIL:

* warm still uses old failed path or creates same failure candidate

INCONCLUSIVE:

* run ids missing, Claude Code unavailable, or evidence insufficient

## Notes

* Do not claim causal proof without controlled cold/warm evidence.
* created=0 is necessary but not sufficient by itself.
