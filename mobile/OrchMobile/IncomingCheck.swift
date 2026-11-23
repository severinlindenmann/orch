import Foundation

/// What the phone does with one message from a workspace (contracts/msgsig.md, receiver steps).
enum IncomingCheck {
    typealias Verdict = SignedCheck.Verdict

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
        shown(m, me: me, accepted: accepted, hints: hints, nowMs: nowMs, seen: seen).0
    }

    /// The check plus the copy to show (ORCH-1296, design section 7): for a signed message it is rebuilt from the
    /// signed bytes, never from the relay's JSON fields; an unsigned one (until the hard cut) stays as it came.
    static func shown(_ m: TextMessage, me: String, accepted: [String: [[UInt8]]], hints: [String: [UInt8]],
                      nowMs: Int64 = MessageSigner.nowMs(), seen: Set<[String]> = []) -> (Verdict, TextMessage?) {
        let (v, s) = SignedCheck.run(envelope: m.envelope?.wire, from: m.from, id: m.id, type: m.type, me: me,
                                     accepted: accepted, hints: hints, nowMs: nowMs, seen: seen)
        switch v {
        case .unsigned: return (v, m)
        case .refused: return (v, nil)
        case .ok, .held:
            guard let s, let r = rebuilt(m, s) else { return (.refused("signed_mismatch"), nil) }
            return (v, r)
        }
    }

    static func shown(_ q: QuestionMessage, me: String, accepted: [String: [[UInt8]]], hints: [String: [UInt8]],
                      nowMs: Int64 = MessageSigner.nowMs()) -> (Verdict, QuestionMessage?) {
        let (v, s) = SignedCheck.run(envelope: q.envelope?.wire, from: q.from, id: q.id, type: q.type, me: me,
                                     accepted: accepted, hints: hints, nowMs: nowMs)
        switch v {
        case .unsigned: return (v, q)
        case .refused: return (v, nil)
        case .ok, .held:
            guard let s, let r = rebuilt(q, s) else { return (.refused("signed_mismatch"), nil) }
            return (v, r)
        }
    }

    /// The text as the workspace signed it. Only the display key (a label like DM1-12, not signed) comes from the relay.
    static func rebuilt(_ m: TextMessage, _ s: [String: MessageSignature.JSON]) -> TextMessage? {
        guard case let .string(to)? = s["to"], let created = s["created_ms"]?.int,
              let body: TextBody = decode(s["body"]) else { return nil }
        var out = TextMessage(id: m.id, from: m.from, to: to, type: m.type, createdAt: SignedCheck.iso(created),
                              ticket: s["ticket"]?.string, body: body, key: m.key, replyTo: s["reply_to"]?.string)
        out.envelope = m.envelope
        return out
    }

    /// The question as the workspace signed it (text, options, recommended, scope, ticket); display key from the relay.
    static func rebuilt(_ q: QuestionMessage, _ s: [String: MessageSignature.JSON]) -> QuestionMessage? {
        guard case let .string(to)? = s["to"], let created = s["created_ms"]?.int,
              let body: QuestionBody = decode(s["body"]) else { return nil }
        var out = QuestionMessage(schema: q.schema, id: q.id, from: q.from, to: to, type: q.type,
                                  createdAt: SignedCheck.iso(created), ticket: s["ticket"]?.string, body: body, key: q.key)
        out.envelope = q.envelope
        return out
    }

    private static func decode<T: Decodable>(_ j: MessageSignature.JSON?) -> T? {
        guard let j, case .object = j, let data = try? JSONSerialization.data(withJSONObject: SignedCheck.plain(j)) else { return nil }
        return try? JSONCoding.decoder.decode(T.self, from: data)
    }
}
