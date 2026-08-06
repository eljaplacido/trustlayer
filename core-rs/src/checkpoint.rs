//! Signed chain checkpoints (ADR-017 §5).
//!
//! A [`crate::integrity`] chain proves the log is internally consistent, but
//! consistency alone does not stop an operator who controls the whole store
//! from rebuilding *both* the events and the chain over them. What defeats
//! that is a commitment published outside the store's control.
//!
//! A checkpoint is that commitment: the chain head at a point in time, signed
//! with a key the store holds but an auditor can verify against a public key
//! they were given in advance. Because the head hash commits to every prior
//! event in the agent's chain, one checkpoint pins the whole prefix — a
//! rebuilt log cannot reproduce it without the private key.
//!
//! **Unsigned checkpoints are still emitted** when no key is configured. An
//! unsigned checkpoint archived off-box (mailed to an auditor, committed to a
//! repository, written to a WORM bucket) still pins the prefix; it just moves
//! the trust anchor from a signature to wherever the copy lives. Emitting
//! nothing would be strictly worse.
//!
//! ## What a checkpoint does not prove
//!
//! It says nothing about whether events *should* have been recorded — an event
//! never submitted to the store is invisible to every mechanism here. It
//! attests to what the store holds, not to the completeness of what the agent
//! chose to emit.

use std::fs;
use std::path::Path;

use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey, SECRET_KEY_LENGTH};
use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};
use crate::integrity::{decode_hex_into, encode_hex, EventHash, Seq};

/// Default number of appends between checkpoints.
pub const DEFAULT_CHECKPOINT_EVERY: u64 = 1000;

/// Default wall-clock interval between checkpoints, in seconds.
pub const DEFAULT_CHECKPOINT_INTERVAL_SECS: i64 = 3600;

/// A signed (or unsigned) commitment to one agent's chain head.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Checkpoint {
    pub agent_id: String,
    /// Chain position this checkpoint commits to.
    pub seq: Seq,
    /// Hash at `seq` — commits to every entry from genesis up to it.
    pub head_hash: EventHash,
    /// RFC 3339, from the store's clock.
    pub created_at: String,
    /// Ed25519 public key, lowercase hex. Absent when unsigned.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub public_key: Option<String>,
    /// Ed25519 signature over [`checkpoint_preimage`], lowercase hex.
    /// Absent when unsigned.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
}

impl Checkpoint {
    /// True when this checkpoint carries both a key and a signature.
    ///
    /// Note this reports *presence*, not validity — [`verify_checkpoint`]
    /// decides validity. The two are kept separate so a UI can distinguish
    /// "unsigned" from "signed but broken", which are very different findings.
    pub fn is_signed(&self) -> bool {
        self.public_key.is_some() && self.signature.is_some()
    }
}

/// Bytes an auditor must reconstruct to verify a checkpoint offline.
///
/// A canonical JSON object with lexicographically ordered keys, matching the
/// convention in [`crate::integrity::canonical_event_json`]. Building an
/// object rather than concatenating fields means no `agent_id` can be crafted
/// to impersonate a different (seq, hash) pair by smuggling a separator.
///
/// This form is normative: it is documented in `spec/v0.1/05-http-api.md` so
/// verification does not require this implementation.
pub fn checkpoint_preimage(
    agent_id: &str,
    seq: Seq,
    head_hash: EventHash,
    created_at: &str,
) -> String {
    // serde_json::Map is BTreeMap-backed, so keys serialise in sorted order.
    serde_json::json!({
        "agent_id": agent_id,
        "created_at": created_at,
        "head_hash": head_hash.to_hex(),
        "seq": seq.get(),
    })
    .to_string()
}

/// Holds the Ed25519 key used to sign checkpoints.
///
/// Deliberately **cannot generate a key**. A key minted inside a process that
/// also writes the log is a key an operator can silently re-mint after
/// rewriting history; generation belongs outside, in whatever key management
/// the deployment already trusts. See `docs/SCALING.md` for the one-liner.
pub struct CheckpointSigner {
    key: SigningKey,
}

impl std::fmt::Debug for CheckpointSigner {
    /// Never renders the private key — a `{:?}` in a log line must not leak it.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CheckpointSigner")
            .field("public_key", &self.public_key_hex())
            .finish_non_exhaustive()
    }
}

impl CheckpointSigner {
    /// Build from a 32-byte seed in lowercase hex (64 characters).
    pub fn from_hex(seed_hex: &str) -> Result<Self> {
        let mut seed = [0u8; SECRET_KEY_LENGTH];
        decode_hex_into(seed_hex.trim(), &mut seed, "signing key")?;
        Ok(Self {
            key: SigningKey::from_bytes(&seed),
        })
    }

    /// Build from a file containing the hex seed.
    ///
    /// Refuses a group- or world-readable file on Unix: a signing key that
    /// anyone on the box can read provides no assurance, and failing loudly is
    /// better than emitting checkpoints that look authoritative but are not.
    pub fn from_file(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(path)?.permissions().mode();
            if mode & 0o077 != 0 {
                return Err(Error::Integrity(format!(
                    "signing key {} is readable by group or others (mode {:o}); \
                     chmod 600 it before use",
                    path.display(),
                    mode & 0o777
                )));
            }
        }
        let contents = fs::read_to_string(path)?;
        Self::from_hex(&contents)
    }

    /// Resolve a signer from `TRUSTLAYER_SIGNING_KEY`.
    ///
    /// The value is a path when it points at an existing file, otherwise it is
    /// treated as a hex seed. Unset returns `Ok(None)` — unsigned checkpoints
    /// are a supported mode, not an error. A value that is set but unusable is
    /// an error: silently degrading to unsigned would let a deployment believe
    /// it is signing when it is not.
    pub fn from_env() -> Result<Option<Self>> {
        let Ok(raw) = std::env::var("TRUSTLAYER_SIGNING_KEY") else {
            return Ok(None);
        };
        let raw = raw.trim();
        if raw.is_empty() {
            return Ok(None);
        }
        let path = Path::new(raw);
        if path.is_file() {
            Self::from_file(path).map(Some)
        } else {
            Self::from_hex(raw).map(Some)
        }
    }

    /// The public key, lowercase hex — hand this to auditors.
    pub fn public_key_hex(&self) -> String {
        encode_hex(self.key.verifying_key().as_bytes())
    }

    /// Sign a checkpoint over the agent's chain head.
    pub fn sign(
        &self,
        agent_id: &str,
        seq: Seq,
        head_hash: EventHash,
        created_at: &str,
    ) -> Checkpoint {
        let preimage = checkpoint_preimage(agent_id, seq, head_hash, created_at);
        let signature: Signature = self.key.sign(preimage.as_bytes());
        Checkpoint {
            agent_id: agent_id.to_string(),
            seq,
            head_hash,
            created_at: created_at.to_string(),
            public_key: Some(self.public_key_hex()),
            signature: Some(encode_hex(&signature.to_bytes())),
        }
    }
}

/// Build an unsigned checkpoint. Used when no signing key is configured.
pub fn unsigned_checkpoint(
    agent_id: &str,
    seq: Seq,
    head_hash: EventHash,
    created_at: &str,
) -> Checkpoint {
    Checkpoint {
        agent_id: agent_id.to_string(),
        seq,
        head_hash,
        created_at: created_at.to_string(),
        public_key: None,
        signature: None,
    }
}

/// Verify a checkpoint's signature against the key it carries.
///
/// Returns `Ok(false)` for an unsigned checkpoint — that is a fact about it,
/// not a failure. Returns `Err` when a checkpoint claims to be signed but the
/// signature does not hold, because a broken signature is a much stronger
/// signal than a missing one and must not be reported as a mere `false`.
///
/// **This only proves the holder of the private key produced the checkpoint.**
/// An auditor must additionally check that the key is the one they were given
/// out of band — verifying against a key transported inside the same response
/// proves nothing on its own.
pub fn verify_checkpoint(checkpoint: &Checkpoint) -> Result<bool> {
    let (Some(public_key), Some(signature)) = (&checkpoint.public_key, &checkpoint.signature)
    else {
        return Ok(false);
    };

    let mut key_bytes = [0u8; 32];
    decode_hex_into(public_key, &mut key_bytes, "public key")?;
    let verifying = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|e| Error::Integrity(format!("malformed public key: {e}")))?;

    let mut sig_bytes = [0u8; 64];
    decode_hex_into(signature, &mut sig_bytes, "signature")?;
    let signature = Signature::from_bytes(&sig_bytes);

    let preimage = checkpoint_preimage(
        &checkpoint.agent_id,
        checkpoint.seq,
        checkpoint.head_hash,
        &checkpoint.created_at,
    );

    // verify_strict rejects small-order public keys, which verify() accepts.
    // For an audit artifact the stricter check is the correct one.
    verifying
        .verify_strict(preimage.as_bytes(), &signature)
        .map_err(|_| {
            Error::Integrity(format!(
                "checkpoint for agent {:?} at seq {} has an invalid signature",
                checkpoint.agent_id, checkpoint.seq
            ))
        })?;
    Ok(true)
}

/// When to emit a checkpoint.
///
/// Both triggers apply — whichever fires first. The count trigger bounds how
/// many events can be written without a commitment; the time trigger bounds
/// how long a low-traffic agent goes uncommitted. A quiet agent that emits ten
/// events a day would otherwise wait months for a count-only checkpoint.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CheckpointPolicy {
    /// Appends between checkpoints. `None` disables the count trigger.
    pub every_events: Option<u64>,
    /// Seconds between checkpoints. `None` disables the time trigger.
    pub interval_secs: Option<i64>,
}

impl Default for CheckpointPolicy {
    fn default() -> Self {
        Self {
            every_events: Some(DEFAULT_CHECKPOINT_EVERY),
            interval_secs: Some(DEFAULT_CHECKPOINT_INTERVAL_SECS),
        }
    }
}

impl CheckpointPolicy {
    /// Disable checkpointing entirely.
    pub const DISABLED: CheckpointPolicy = CheckpointPolicy {
        every_events: None,
        interval_secs: None,
    };

    /// True when nothing will ever trigger.
    pub fn is_disabled(&self) -> bool {
        self.every_events.is_none() && self.interval_secs.is_none()
    }

    /// Should a checkpoint be written now?
    ///
    /// `since_last` counts appends since the previous checkpoint for this
    /// agent; `elapsed_secs` is the wall-clock gap. A `since_last` of zero
    /// never triggers: re-committing an unchanged head produces noise with no
    /// new information.
    pub fn should_checkpoint(&self, since_last: u64, elapsed_secs: i64) -> bool {
        if since_last == 0 {
            return false;
        }
        let by_count = self.every_events.is_some_and(|n| since_last >= n);
        let by_time = self.interval_secs.is_some_and(|s| elapsed_secs >= s);
        by_count || by_time
    }

    /// Read from `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY` and
    /// `TRUSTLAYER_INTEGRITY_CHECKPOINT_INTERVAL_SECS`.
    ///
    /// `0` disables that trigger. Unparseable values fall back to the default
    /// for that trigger; the caller decides whether to warn.
    pub fn from_env() -> Self {
        fn read(name: &str, default: i64) -> Option<i64> {
            match std::env::var(name) {
                Ok(raw) => match raw.trim().parse::<i64>() {
                    Ok(0) => None,
                    Ok(v) if v > 0 => Some(v),
                    _ => Some(default),
                },
                Err(_) => Some(default),
            }
        }
        CheckpointPolicy {
            every_events: read(
                "TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY",
                DEFAULT_CHECKPOINT_EVERY as i64,
            )
            .map(|v| v as u64),
            interval_secs: read(
                "TRUSTLAYER_INTEGRITY_CHECKPOINT_INTERVAL_SECS",
                DEFAULT_CHECKPOINT_INTERVAL_SECS,
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed seed, so signature bytes are reproducible across runs. Test-only
    /// — a real deployment generates one per `docs/SCALING.md`.
    const SEED: &str = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60";

    fn signer() -> CheckpointSigner {
        CheckpointSigner::from_hex(SEED).expect("seed parses")
    }

    fn head() -> EventHash {
        EventHash::from_hex(&"ab".repeat(32)).expect("hash parses")
    }

    #[test]
    fn signed_checkpoint_verifies() {
        let cp = signer().sign("agent-a", Seq::new(42), head(), "2026-08-05T10:00:00+00:00");

        assert!(cp.is_signed());
        assert!(verify_checkpoint(&cp).expect("verifies"));
    }

    #[test]
    fn unsigned_checkpoint_reports_false_not_an_error() {
        let cp = unsigned_checkpoint("agent-a", Seq::new(1), head(), "2026-08-05T10:00:00+00:00");

        assert!(!cp.is_signed());
        assert!(!verify_checkpoint(&cp).expect("unsigned is not an error"));
    }

    #[test]
    fn public_key_is_stable_for_a_seed() {
        assert_eq!(signer().public_key_hex(), signer().public_key_hex());
        assert_eq!(signer().public_key_hex().len(), 64);
    }

    #[test]
    fn tampering_with_the_head_hash_invalidates_the_signature() {
        let mut cp = signer().sign("agent-a", Seq::new(42), head(), "2026-08-05T10:00:00+00:00");
        cp.head_hash = EventHash::from_hex(&"cd".repeat(32)).expect("hash");

        let err = verify_checkpoint(&cp).expect_err("must not verify");
        assert!(err.to_string().contains("invalid signature"), "{err}");
    }

    #[test]
    fn tampering_with_the_seq_invalidates_the_signature() {
        let mut cp = signer().sign("agent-a", Seq::new(42), head(), "2026-08-05T10:00:00+00:00");
        cp.seq = Seq::new(43);

        assert!(verify_checkpoint(&cp).is_err());
    }

    #[test]
    fn tampering_with_the_agent_id_invalidates_the_signature() {
        // A checkpoint replayed under another agent's name would otherwise let
        // one agent's evidence stand in for another's.
        let mut cp = signer().sign("agent-a", Seq::new(42), head(), "2026-08-05T10:00:00+00:00");
        cp.agent_id = "agent-b".into();

        assert!(verify_checkpoint(&cp).is_err());
    }

    #[test]
    fn tampering_with_created_at_invalidates_the_signature() {
        let mut cp = signer().sign("agent-a", Seq::new(42), head(), "2026-08-05T10:00:00+00:00");
        cp.created_at = "2026-08-05T11:00:00+00:00".into();

        assert!(verify_checkpoint(&cp).is_err());
    }

    #[test]
    fn a_signature_from_a_different_key_is_rejected() {
        let other = CheckpointSigner::from_hex(&"11".repeat(32)).expect("seed");
        let mine = signer().sign("agent-a", Seq::new(1), head(), "2026-08-05T10:00:00+00:00");
        let mut forged = other.sign("agent-a", Seq::new(1), head(), "2026-08-05T10:00:00+00:00");

        // Claim my key while carrying their signature.
        forged.public_key = mine.public_key.clone();

        assert!(verify_checkpoint(&forged).is_err());
    }

    #[test]
    fn preimage_is_canonical_and_key_sorted() {
        let preimage = checkpoint_preimage("a", Seq::new(2), head(), "2026-08-05T10:00:00+00:00");

        assert!(
            !preimage.contains(' '),
            "preimage must be compact: {preimage}"
        );
        let agent = preimage.find("agent_id").expect("agent_id");
        let created = preimage.find("created_at").expect("created_at");
        let hash = preimage.find("head_hash").expect("head_hash");
        let seq = preimage.find("\"seq\"").expect("seq");
        assert!(
            agent < created && created < hash && hash < seq,
            "{preimage}"
        );
    }

    #[test]
    fn preimage_is_unambiguous_across_field_boundaries() {
        // If fields were concatenated, ("a|b", 1) and ("a", "b|1") could
        // collide. The JSON object form makes that impossible; assert it.
        let one = checkpoint_preimage("a\":2,\"x", Seq::new(1), head(), "t");
        let two = checkpoint_preimage("a", Seq::new(1), head(), "t");
        assert_ne!(one, two);
    }

    #[test]
    fn malformed_seed_is_rejected() {
        for bad in ["", "zz", &"a".repeat(63), &"z".repeat(64)] {
            assert!(CheckpointSigner::from_hex(bad).is_err(), "accepted {bad:?}");
        }
    }

    #[test]
    fn checkpoint_serde_round_trips_and_omits_absent_signature() {
        let cp = unsigned_checkpoint("a", Seq::new(1), head(), "2026-08-05T10:00:00+00:00");
        let line = serde_json::to_string(&cp).expect("serialise");

        assert!(!line.contains("signature"), "{line}");
        assert!(!line.contains("public_key"), "{line}");
        let back: Checkpoint = serde_json::from_str(&line).expect("deserialise");
        assert_eq!(back, cp);
    }

    #[test]
    fn signed_checkpoint_serde_round_trips() {
        let cp = signer().sign("a", Seq::new(7), head(), "2026-08-05T10:00:00+00:00");
        let line = serde_json::to_string(&cp).expect("serialise");
        let back: Checkpoint = serde_json::from_str(&line).expect("deserialise");

        assert_eq!(back, cp);
        assert!(verify_checkpoint(&back).expect("verifies"));
    }

    #[test]
    fn debug_never_renders_the_private_key() {
        let rendered = format!("{:?}", signer());
        assert!(!rendered.contains(SEED), "private key leaked: {rendered}");
        assert!(rendered.contains("public_key"));
    }

    #[test]
    fn policy_triggers_on_count() {
        let policy = CheckpointPolicy {
            every_events: Some(10),
            interval_secs: None,
        };
        assert!(!policy.should_checkpoint(9, 0));
        assert!(policy.should_checkpoint(10, 0));
        assert!(policy.should_checkpoint(11, 0));
    }

    #[test]
    fn policy_triggers_on_elapsed_time() {
        let policy = CheckpointPolicy {
            every_events: None,
            interval_secs: Some(60),
        };
        assert!(!policy.should_checkpoint(1, 59));
        assert!(policy.should_checkpoint(1, 60));
    }

    #[test]
    fn policy_never_triggers_without_new_events() {
        // Re-committing an unchanged head is noise, not evidence.
        let policy = CheckpointPolicy::default();
        assert!(!policy.should_checkpoint(0, 1_000_000));
    }

    #[test]
    fn disabled_policy_never_triggers() {
        assert!(CheckpointPolicy::DISABLED.is_disabled());
        assert!(!CheckpointPolicy::DISABLED.should_checkpoint(u64::MAX, i64::MAX));
    }

    #[test]
    fn default_policy_matches_the_documented_constants() {
        let policy = CheckpointPolicy::default();
        assert_eq!(policy.every_events, Some(DEFAULT_CHECKPOINT_EVERY));
        assert_eq!(policy.interval_secs, Some(DEFAULT_CHECKPOINT_INTERVAL_SECS));
        assert!(!policy.is_disabled());
    }
}
