import Foundation

/// The receiver steps for one message from a workspace (contracts/msgsig.md), shared by the app and the
/// notification extension (ORCH-1296). Only `MessageSignature` is needed, so the extension compiles it too.
enum SignedCheck {
    enum Verdict: Equatable {
        /// Signed by the key the person accepted: show what was signed.
        case ok
        /// Validly signed by the workspace's listed key, but not accepted yet: held, shown only after Accept.
        case held
        /// A wrong, missing or changed signature, or the relay's routing fields differ from the signed ones: refused.
        case refused(String)
        /// No signature (until the hard cut, ORCH-1205).
        case unsigned
    }

    /// `envelope` is the wire object `{sig_v, key_id, signed, sig}` or nil; `from`, `id` and `type` are the relay's
    /// routing fields (where it filed the message); they must match the signed ones. Returns the verdict and, for
    /// `ok` and `held`, the signed message: the only copy the phone shows.
    static func run(envelope: [String: Any]?, from: String, id: String, type: String, me: String,
                    accepted: [String: [[UInt8]]], hints: [String: [UInt8]], nowMs: Int64,
                    seen: Set<[String]> = []) -> (Verdict, [String: MessageSignature.JSON]?) {
        // Once a person accepted the workspace, an unsigned message from it is refused: the relay may have
        // stripped the signature (no downgrade).
        guard let envelope else { return (accepted[from] == nil ? .unsigned : .refused("missing_signature"), nil) }
        func routed(_ s: [String: MessageSignature.JSON], _ v: Verdict) -> (Verdict, [String: MessageSignature.JSON]?) {
            guard s["id"]?.string == id, s["from"]?.string == from, s["type"]?.string == type else {
                return (.refused("signed_mismatch"), nil)
            }
            return (v, s)
        }
        do {
            let s = try MessageSignature.receiverCheck(envelope, me: me, accepted: accepted, nowMs: nowMs, seen: seen)
            return routed(s, .ok)
        } catch let r as MessageSignature.Refused where r.code == "unknown_key" {
            // Not accepted (yet): held only when the workspace's listed key signed it validly; else refused.
            guard let hint = hints[from] else { return (.refused("unknown_key"), nil) }
            do {
                let s = try MessageSignature.receiverCheck(envelope, me: me, accepted: [from: [hint]], nowMs: nowMs, seen: seen)
                return routed(s, .held)
            } catch let r2 as MessageSignature.Refused {
                return (.refused(r2.code), nil)
            } catch { return (.refused("bad_envelope"), nil) }
        } catch let r as MessageSignature.Refused {
            return (.refused(r.code), nil)
        } catch { return (.refused("bad_envelope"), nil) }
    }

    /// A signed value as JSONSerialization objects (to decode it with the app's Codable types).
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

    /// `created_ms` as the ISO text the app's lists sort and show by.
    static func iso(_ ms: Int64) -> String {
        ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(ms) / 1000))
    }
}
