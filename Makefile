.PHONY: verify test security compliance

verify:
	./scripts/verify.sh

test:
	./scripts/verify.sh test

security:
	./scripts/verify.sh security

compliance:
	./scripts/verify.sh compliance
