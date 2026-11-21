import Foundation

/// What a push from a workspace may show (ORCH-1296, design ORCH-1198 section 7). The relay writes the push text, so
/// the notification extension shows a message's words only when the workspace's signature over them checks out with
/// the key the person accepted; otherwise only "New message from <workspace>" and never an answer button.
/// Compiled into the app (tests) and the notification extension.
enum PushCheck {
    struct Shown: Equatable {
        let title: String
        let body: String
        /// The words come from the signed message; only then may an answer button stay.
        let verified: Bool
    }

    /// The same cap the relay uses for its own push text.
    static let maxChars = 120
    /// A workspace name the relay sends is shown at most this long.
    static let maxNameChars = 40

    static func generic(_ name: String) -> String { name.isEmpty ? "New message" : "New message from \(name)" }

    /// `userInfo` is the push payload; `title` and `body` are what the relay put in `aps.alert`.
    /// `names` are the workspace names saved at Accept: a checked push is titled with that name, never the relay's.
    static func decide(_ userInfo: [AnyHashable: Any], title: String, body: String, me: String?,
                       accepted: [String: [[UInt8]]], names: [String: String] = [:], nowMs: Int64) -> Shown {
        // The plain notice names the workspace by the name saved at Accept when there is one; otherwise the relay's
        // name, cut short (a name, not room for a message).
        let ws = userInfo["workspace"] as? String ?? ""
        let name = names[ws] ?? String(title.prefix(maxNameChars))
        let fallback = Shown(title: name, body: generic(name), verified: false)
        guard !ws.isEmpty, let me, !me.isEmpty else { return fallback }
        let id: String, type: String
        if let q = userInfo["message_id"] as? String {
            id = q; type = "question"
        } else if let t = userInfo["text_id"] as? String {
            id = t; type = (userInfo["msg_type"] as? String) ?? "text"
        } else {
            return fallback
        }
        // Not accepted yet (held) counts as not checked: the push never shows it, the app holds it until Accept.
        let (verdict, s) = SignedCheck.run(envelope: userInfo["envelope"] as? [String: Any], from: ws, id: id, type: type,
                                           me: me, accepted: accepted, hints: [:], nowMs: nowMs)
        guard verdict == .ok, let s, let text = pushText(s, key: userInfo["key"] as? String) else { return fallback }
        return Shown(title: name, body: text, verified: true)
    }

    /// The push line from the signed message, as the relay would write it: "<key> · <update title>: <first line>"
    /// or "<key> · <text>", cut to 120 characters. `key` (DM1-12) is the relay's label; it is not signed.
    static func pushText(_ s: [String: MessageSignature.JSON], key: String?) -> String? {
        guard let body = s["body"]?.object, let text = body["text"]?.string else { return nil }
        var line = text
        if let t = body["update"]?.object?["title"]?.string {
            line = "\(t): \(text.split(separator: "\n", omittingEmptySubsequences: false).first.map(String.init) ?? "")"
        }
        if let key, key.range(of: "^[A-Z0-9]{2,4}-[1-9][0-9]{0,8}$", options: .regularExpression) != nil {
            line = "\(key) · \(line)"
        }
        let cut = String(line.prefix(maxChars))
        return cut.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : cut
    }
}
