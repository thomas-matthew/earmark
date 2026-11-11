"""Which Claude model each job uses. Full model IDs rather than aliases, so a model changes only
when it is changed here, not when the account default or an alias moves on."""

WRITER = "claude-fable-5-2"  # gathers sources, writes the script and fixes it after review
REVIEWER = "claude-fable-5-2"  # checks the script against the sources
RELEVANCE = "claude-sonnet-5-5"  # include-or-skip check for Reddit and X items
DOCTOR = "claude-haiku-5-5"  # `earmark doctor` login check; any model works
