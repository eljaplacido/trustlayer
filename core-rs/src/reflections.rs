//! Read-only access to Hermes-generated reflection notes.
//!
//! Hermes ([[ADR-002]]) writes one reflection per `reflect()` pass to
//! `<vault>/05_Reflections/reflection-<date>.md`. The dashboard's Reflections
//! pane surfaces these — generation stays Hermes's job (the Python CLI or the
//! `trustlayer_hermes_reflect` MCP tool); the sidecar only lists and serves.
//!
//! Every filename that crosses the HTTP boundary is validated against
//! [`is_safe_name`] so a crafted `:name` path segment cannot escape the
//! reflections directory.

use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::error::{Error, Result};

const REFLECTION_SUBDIR: &str = "05_Reflections";
const PREFIX: &str = "reflection-";
const SUFFIX: &str = ".md";

/// Metadata for one reflection note — what `GET /v1/reflections` returns.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ReflectionMeta {
    /// File name, e.g. `reflection-2026-05-22.md`. Safe to use as a path param.
    pub name: String,
    /// Date portion parsed out of the file name, e.g. `2026-05-22`.
    pub date: String,
}

/// One reflection note with its raw markdown body.
#[derive(Debug, Clone, Serialize)]
pub struct Reflection {
    pub name: String,
    pub date: String,
    pub content: String,
}

/// `true` iff `name` is a bare `reflection-*.md` file name with no path
/// separators or parent-directory components. The HTTP layer must reject
/// anything for which this returns `false`.
pub fn is_safe_name(name: &str) -> bool {
    !name.is_empty()
        && name.starts_with(PREFIX)
        && name.ends_with(SUFFIX)
        && !name.contains('/')
        && !name.contains('\\')
        && !name.contains("..")
        && !name.contains('\0')
}

fn date_of(name: &str) -> String {
    name.strip_prefix(PREFIX)
        .and_then(|s| s.strip_suffix(SUFFIX))
        .unwrap_or(name)
        .to_string()
}

/// List every reflection note in `<vault>/05_Reflections/`, newest first.
/// A missing directory yields an empty list rather than an error — a vault
/// that has never been reflected over is a normal state.
pub fn list(vault: &Path) -> Result<Vec<ReflectionMeta>> {
    let dir = vault.join(REFLECTION_SUBDIR);
    if !dir.exists() {
        return Ok(Vec::new());
    }
    let mut metas: Vec<ReflectionMeta> = Vec::new();
    for entry in std::fs::read_dir(&dir)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        if !is_safe_name(&name) {
            continue;
        }
        metas.push(ReflectionMeta {
            date: date_of(&name),
            name,
        });
    }
    // File names embed ISO dates, so a lexical sort is a chronological sort.
    metas.sort_by(|a, b| b.name.cmp(&a.name));
    Ok(metas)
}

/// Read one reflection note. Returns `Ok(None)` when the (validated) name
/// does not exist; `Err` only for an unsafe name or a genuine IO failure.
pub fn read(vault: &Path, name: &str) -> Result<Option<Reflection>> {
    if !is_safe_name(name) {
        return Err(Error::Io(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("unsafe reflection name: {name}"),
        )));
    }
    let path: PathBuf = vault.join(REFLECTION_SUBDIR).join(name);
    if !path.is_file() {
        return Ok(None);
    }
    let content = std::fs::read_to_string(&path)?;
    Ok(Some(Reflection {
        date: date_of(name),
        name: name.to_string(),
        content,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tempdir() -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("trustlayer-reflections-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(p.join(REFLECTION_SUBDIR)).expect("mkdir");
        p
    }

    fn write_reflection(vault: &Path, name: &str, body: &str) {
        std::fs::write(vault.join(REFLECTION_SUBDIR).join(name), body)
            .expect("write reflection");
    }

    #[test]
    fn safe_name_accepts_real_reflection_files() {
        assert!(is_safe_name("reflection-2026-05-22.md"));
    }

    #[test]
    fn safe_name_rejects_traversal_and_junk() {
        assert!(!is_safe_name("../../etc/passwd"));
        assert!(!is_safe_name("reflection-../x.md"));
        assert!(!is_safe_name("reflection-2026.md/../../x"));
        assert!(!is_safe_name("notes.md"));
        assert!(!is_safe_name("reflection-2026-05-22.txt"));
        assert!(!is_safe_name(""));
    }

    #[test]
    fn list_missing_dir_returns_empty() {
        let mut p = std::env::temp_dir();
        p.push(format!("trustlayer-no-vault-{}", uuid::Uuid::new_v4()));
        assert!(list(&p).expect("list").is_empty());
    }

    #[test]
    fn list_returns_reflections_newest_first() {
        let vault = tempdir();
        write_reflection(&vault, "reflection-2026-05-10.md", "old");
        write_reflection(&vault, "reflection-2026-05-22.md", "new");
        write_reflection(&vault, "stray-note.md", "ignored");
        let metas = list(&vault).expect("list");
        assert_eq!(metas.len(), 2);
        assert_eq!(metas[0].name, "reflection-2026-05-22.md");
        assert_eq!(metas[0].date, "2026-05-22");
        assert_eq!(metas[1].name, "reflection-2026-05-10.md");
    }

    #[test]
    fn read_returns_content() {
        let vault = tempdir();
        write_reflection(&vault, "reflection-2026-05-22.md", "# Reflection\nbody");
        let r = read(&vault, "reflection-2026-05-22.md")
            .expect("read")
            .expect("some");
        assert_eq!(r.date, "2026-05-22");
        assert!(r.content.contains("body"));
    }

    #[test]
    fn read_missing_file_returns_none() {
        let vault = tempdir();
        assert!(read(&vault, "reflection-2099-01-01.md")
            .expect("read")
            .is_none());
    }

    #[test]
    fn read_unsafe_name_is_error() {
        let vault = tempdir();
        assert!(read(&vault, "../../etc/passwd").is_err());
    }
}
