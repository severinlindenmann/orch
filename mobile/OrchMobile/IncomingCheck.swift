import Foundation
import Security

/// The phone's own list of accepted workspaces (ORCH-1204, design ORCH-1027 section 5): the full public key a person
/// accepted for each workspace, kept in the keychain for this device only, never from the relay. Accept is a
/// person's tap in that workspace's chat; withdrawing is always possible.
struct TrustStore: Sendable {
    struct Entry: Codable, Sendable, Equatable {
        let publicKey: String     // base64url raw key
        let acceptedAt: String
    }

    let load: @Sendable () -> [String: Entry]
    let save: @Sendable ([String: Entry]) -> Void

    private static let service = "io.severin.orch.mobile"
    private static let account = "trust-v1"
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static let keychain = TrustStore(
        load: {
            var q = TrustStore.query
            q[kSecReturnData as String] = true
            q[kSecMatchLimit as String] = kSecMatchLimitOne
            var out: AnyObject?
            guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data,
                  let m = try? JSONDecoder().decode([String: Entry].self, from: d) else { return [:] }
            return m
        },
        save: { m in
            SecItemDelete(TrustStore.query as CFDictionary)
            guard !m.isEmpty, let d = try? JSONEncoder().encode(m) else { return }
            var q = TrustStore.query
            q[kSecValueData as String] = d
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            SecItemAdd(q as CFDictionary, nil)
        }
    )

    static func memory() -> TrustStore {
        final class Box: @unchecked Sendable { var m: [String: Entry] = [:] }
        let b = Box()
        return TrustStore(load: { b.m }, save: { b.m = $0 })
    }

    /// Raw accepted keys per workspace, for `MessageSignature.receiverCheck`.
    func accepted() -> [String: [[UInt8]]] {
        load().compactMapValues { e in MessageSignature.b64urlDecodeStrict(e.publicKey).map { [$0] } }
    }

    /// Accept `key` for `workspace` (the person's tap). A weak or malformed key is never accepted.
    @discardableResult
    func accept(_ workspace: String, key: String, now: Date = Date()) -> Bool {
        guard let raw = MessageSignature.b64urlDecodeStrict(key), MessageSignature.publicKeyOK(raw) else { return false }
        var m = load()
        m[workspace] = Entry(publicKey: key, acceptedAt: ISO8601DateFormatter().string(from: now))
        save(m)
        return true
    }

    func withdraw(_ workspace: String) {
        var m = load()
        m[workspace] = nil
        save(m)
    }

    func clear() { save([:]) }
}

/// What the phone does with one message from a workspace (contracts/msgsig.md, receiver steps).
enum IncomingCheck {
    enum Verdict: Equatable {
        /// Signed by the key the person accepted, and the relay's copy says the same: show it.
        case ok
        /// Validly signed by the workspace's listed key, but not accepted yet: held, shown only after Accept.
        case held
        /// A wrong, missing or changed signature, or the relay's copy differs from the signed bytes: refused.
        case refused(String)
        /// No signature (until the hard cut, ORCH-1205).
        case unsigned
    }

    /// The workspace's state as the person sees it on the phone.
    enum SenderState: Equatable { case accepted, notAcceptedYet, changed, noKey }

    static func senderState(_ ws: Workspace, accepted: [String: [[UInt8]]]) -> SenderState {
        guard let hint = ws.signingKey, let raw = MessageSignature.b64urlDecodeStrict(hint.publicKey) else {
            return accepted[ws.id] == nil ? .noKey : .accepted
        }
        guard let mine = accepted[ws.id] else { return .notAcceptedYet }
        return mine.contains(raw) ? .accepted : .changed
    }

    static func check(_ m: TextMessage, me: String, accepted: [String: [[UInt8]]], hints: [String: [UInt8]],
                      nowMs: Int64 = MessageSigner.nowMs(), seen: Set<[String]> = []) -> Verdict {
        // Once a person accepted the workspace, an unsigned message from it is refused: the relay may have
        // stripped the signature (no downgrade).
        guard let e = m.envelope else { return accepted[m.from] == nil ? .unsigned : .refused("missing_signature") }
        let env: [String: Any] = ["sig_v": e.sigV, "key_id": e.keyId, "signed": e.signed, "sig": e.sig]
        do {
            let s = try MessageSignature.receiverCheck(env, me: me, accepted: accepted, nowMs: nowMs, seen: seen)
            return sameAsSigned(m, s) ? .ok : .refused("signed_mismatch")
        } catch let r as MessageSignature.Refused where r.code == "unknown_key" {
            // Not accepted (yet): held only when the workspace's listed key signed it validly; else refused.
            guard let hint = hints[m.from] else { return .refused("unknown_key") }
            do {
                let s = try MessageSignature.receiverCheck(env, me: me, accepted: [m.from: [hint]], nowMs: nowMs, seen: seen)
                return sameAsSigned(m, s) ? .held : .refused("signed_mismatch")
            } catch let r2 as MessageSignature.Refused {
                return .refused(r2.code)
            } catch { return .refused("bad_envelope") }
        } catch let r as MessageSignature.Refused {
            return .refused(r.code)
        } catch { return .refused("bad_envelope") }
    }

    /// The relay's JSON fields must say exactly what the signed bytes say (the phone shows the relay's copy).
    static func sameAsSigned(_ m: TextMessage, _ s: [String: MessageSignature.JSON]) -> Bool {
        guard s["id"]?.string == m.id, s["from"]?.string == m.from, s["type"]?.string == m.type,
              s["ticket"]?.string == m.ticket, s["reply_to"]?.string == m.replyTo,
              let body = s["body"], let data = try? JSONSerialization.data(withJSONObject: plain(body)),
              let signedBody = try? JSONCoding.decoder.decode(TextBody.self, from: data) else { return false }
        if case let .string(to) = s["to"], to != m.to { return false }
        return signedBody == m.body
    }

    static func plain(_ j: MessageSignature.JSON) -> Any {
        switch j {
        case let .object(o): return o.mapValues(plain)
        case let .array(a): return a.map(plain)
        case let .string(s): return s
        case let .int(n): return n
        case let .bool(b): return b
        case .null: return NSNull()
        }
    }
}
