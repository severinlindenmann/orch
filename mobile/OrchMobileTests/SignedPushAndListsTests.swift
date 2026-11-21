@testable import OrchMobile
import CryptoKit
import XCTest

/// ORCH-1296 (design ORCH-1198 section 7): a push shows a workspace's words only when its signature checks out with
/// the accepted key, else "New message from <workspace>" and no answer button; the phone's questions and chat are
/// rebuilt from the signed bytes, never from the relay's JSON fields.
final class SignedPushAndListsTests: XCTestCase {
    private let ws = "ws_abcdefghij"
    private let ph = "ph_abcdefghij"
    private let wsKey = Curve25519.Signing.PrivateKey()
    private var raw: [UInt8] { [UInt8](wsKey.publicKey.rawRepresentation) }

    private func question(_ text: String = "Deploy to staging?", options: [String] = ["yes", "no"],
                          relayText: String? = nil, relayOptions: [String]? = nil, relayTicket: String? = nil,
                          key: Curve25519.Signing.PrivateKey? = nil) throws -> QuestionMessage {
        let body: [String: Any] = ["question_id": "q1", "text": text, "options": options, "recommended": options[0]]
        let d = MessageSigner.Draft(from: ws, to: "phones", type: "question", body: body, ticket: "t_abc123")
        let e = try MessageSigner.envelope(d, key: key ?? wsKey)
        var relayBody = body
        relayBody["text"] = relayText ?? text
        relayBody["options"] = relayOptions ?? options
        relayBody["recommended"] = (relayOptions ?? options)[0]
        let outer: [String: Any] = ["schema": "orch.msg/1", "id": d.id, "from": ws, "to": "phones", "type": "question",
                                    "created_at": "2026-11-21T10:00:00Z", "ticket": relayTicket ?? "t_abc123", "body": relayBody,
                                    "key": "DM1-12", "envelope": e]
        return try JSONCoding.decoder.decode(QuestionMessage.self, from: JSONSerialization.data(withJSONObject: outer))
    }

    // MARK: questions

    func testAQuestionTheRelayChangedShowsTheSignedQuestion() throws {
        let q = try question("Delete the old backups?", options: ["no", "yes"], relayText: "Keep the backups?",
                             relayOptions: ["yes", "no"], relayTicket: "t_zzz999")
        let (v, shown) = IncomingCheck.shown(q, me: ph, accepted: [ws: [raw]], hints: [:])
        XCTAssertEqual(v, .ok)
        XCTAssertEqual(shown?.body.text, "Delete the old backups?")
        XCTAssertEqual(shown?.body.options, ["no", "yes"])
        XCTAssertEqual(shown?.body.recommended, "no")
        XCTAssertEqual(shown?.ticket, "t_abc123")
        XCTAssertEqual(shown?.key, "DM1-12", "the display key is the relay's label")
        XCTAssertEqual(shown?.id, q.id)
    }

    func testAQuestionWithABadSignatureOrUnderAnotherWorkspaceIsRefused() throws {
        let forged = try question(key: Curve25519.Signing.PrivateKey())
        XCTAssertEqual(IncomingCheck.shown(forged, me: ph, accepted: [ws: [raw]], hints: [:]).0, .refused("unknown_key"))
        // The relay files a signed question under another workspace id: refused, not shown there.
        let q = try question()
        let moved = QuestionMessage(schema: q.schema, id: q.id, from: "ws_otherother", to: q.to, type: q.type, createdAt: q.createdAt,
                                    ticket: q.ticket, body: q.body, key: q.key, envelope: q.envelope)
        XCTAssertEqual(IncomingCheck.shown(moved, me: ph, accepted: [ws: [raw], "ws_otherother": [raw]], hints: [:]).0, .refused("signed_mismatch"))
        var stripped = q
        stripped.envelope = nil
        XCTAssertEqual(IncomingCheck.shown(stripped, me: ph, accepted: [ws: [raw]], hints: [:]).0, .refused("missing_signature"))
        XCTAssertEqual(IncomingCheck.shown(stripped, me: ph, accepted: [:], hints: [:]).0, .unsigned, "until the hard cut")
    }

    @MainActor
    func testTheQuestionListShowsSignedQuestionsAndHoldsANewWorkspace() throws {
        let model = AppModel(useMock: true)
        model.testSetWorkspaces([Workspace(id: ws, name: "Dev", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0,
                                           signingKey: WorkspaceKey(alg: "ed25519", publicKey: MessageSignature.b64urlEncode(raw),
                                                                    keyId: MessageSignature.keyId(raw)))])
        let changed = Question(message: try question("Delete the old backups?", relayText: "Keep the backups?"), workspaceName: "Dev")
        XCTAssertTrue(model.testCheckQuestions([changed]).isEmpty, "not accepted yet: not on the list")
        XCTAssertTrue(model.acceptWorkspace(ws, shownFingerprint: MessageSignature.fingerprint(raw)))
        XCTAssertEqual(model.trust.names()[ws], "Dev", "the name the person saw is kept for checked pushes")
        let list = model.testCheckQuestions([changed])
        XCTAssertEqual(list.map(\.message.body.text), ["Delete the old backups?"])
        XCTAssertEqual(list.first?.workspaceName, "Dev")
    }

    // MARK: push

    private func push(_ q: QuestionMessage, relayBody: String) throws -> [AnyHashable: Any] {
        let e = try XCTUnwrap(q.envelope)
        return ["aps": ["alert": ["title": "Dev", "body": relayBody], "mutable-content": 1], "workspace": ws,
                "message_id": q.id, "key": "DM1-12", "envelope": e.wire]
    }

    private let now = MessageSigner.nowMs()

    func testAPushWithChangedTextShowsOnlyNewMessage() throws {
        let q = try question("Delete the old backups?")
        // The relay's alert text is never used; only the signed text or the plain line.
        let ok = PushCheck.decide(try push(q, relayBody: "Keep the backups?"), title: "Dev", body: "Keep the backups?", me: ph,
                                  accepted: [ws: [raw]], nowMs: now)
        XCTAssertEqual(ok, PushCheck.Shown(title: "Dev", body: "DM1-12 · Delete the old backups?", verified: true))
        let named = PushCheck.decide(try push(q, relayBody: "x"), title: "Bank Login", body: "x", me: ph, accepted: [ws: [raw]],
                                     names: [ws: "Dev"], nowMs: now)
        XCTAssertEqual(named.title, "Dev", "a checked push carries the name saved at Accept, not the relay's title")

        var info = try push(q, relayBody: "x")
        var env = try XCTUnwrap(info["envelope"] as? [String: Any])
        var signed = try XCTUnwrap(MessageSignature.b64urlDecodeStrict(try XCTUnwrap(env["signed"] as? String)))
        signed[signed.firstIndex(of: UInt8(ascii: "D"))!] = UInt8(ascii: "K")   // changed text inside the signed bytes
        env["signed"] = MessageSignature.b64urlEncode(signed)
        info["envelope"] = env
        let changed = PushCheck.decide(info, title: "Dev", body: "Keep the old backups?", me: ph, accepted: [ws: [raw]], nowMs: now)
        XCTAssertEqual(changed, PushCheck.Shown(title: "Dev", body: "New message from Dev", verified: false))
    }

    func testAPushIsPlainWhenUnsignedNotAcceptedForgedOrNotForThisPhone() throws {
        let q = try question()
        var unsigned = try push(q, relayBody: "Deploy to staging?")
        unsigned["envelope"] = nil
        let plain = PushCheck.Shown(title: "Dev", body: "New message from Dev", verified: false)
        XCTAssertEqual(PushCheck.decide(unsigned, title: "Dev", body: "Deploy to staging?", me: ph, accepted: [ws: [raw]], nowMs: now), plain)
        XCTAssertEqual(PushCheck.decide(unsigned, title: "Dev", body: "Deploy to staging?", me: ph, accepted: [:], nowMs: now), plain,
                       "unsigned text is never shown in a push, even before the hard cut")
        XCTAssertEqual(PushCheck.decide(try push(q, relayBody: "x"), title: "Dev", body: "x", me: ph, accepted: [:], nowMs: now), plain,
                       "a workspace not accepted yet")
        XCTAssertEqual(PushCheck.decide(try push(try question(key: Curve25519.Signing.PrivateKey()), relayBody: "x"), title: "Dev", body: "x",
                                        me: ph, accepted: [ws: [raw]], nowMs: now), plain)
        XCTAssertEqual(PushCheck.decide(try push(q, relayBody: "x"), title: "Dev", body: "x", me: nil, accepted: [ws: [raw]], nowMs: now), plain,
                       "no phone id (not paired)")
        var otherId = try push(q, relayBody: "x")
        otherId["message_id"] = "m_aaaaaaaaaaaaaaaa"
        XCTAssertEqual(PushCheck.decide(otherId, title: "Dev", body: "x", me: ph, accepted: [ws: [raw]], nowMs: now), plain,
                       "the signed id must be the pushed id")
        XCTAssertEqual(PushCheck.decide(try push(q, relayBody: "x"), title: "", body: "x", me: ph, accepted: [:], nowMs: now).body, "New message")
        let long = PushCheck.decide(unsigned, title: "Transfer your money now to the account in this notice please", body: "x", me: ph,
                                    accepted: [:], nowMs: now)
        XCTAssertEqual(long.title.count, 40, "the relay's name is cut short")
        XCTAssertEqual(PushCheck.decide(unsigned, title: "Transfer your money now", body: "x", me: ph, accepted: [ws: [raw]],
                                        names: [ws: "Dev"], nowMs: now), plain, "the name saved at Accept wins over the relay's")
    }

    func testATextPushUsesTheSignedUpdateTitleAndFirstLine() throws {
        let d = MessageSigner.Draft(from: ws, to: ph, body: ["text": "All green\nsecond line", "update": ["kind": "result", "title": "Build"]])
        let e = try MessageSigner.envelope(d, key: wsKey)
        let info: [AnyHashable: Any] = ["workspace": ws, "type": "text", "text_id": d.id, "envelope": e]
        XCTAssertEqual(PushCheck.decide(info, title: "Dev", body: "relay words", me: ph, accepted: [ws: [raw]], nowMs: now).body,
                       "Build: All green")
        let long = MessageSigner.Draft(from: ws, to: "phones", body: ["text": String(repeating: "a", count: 300)])
        let info2: [AnyHashable: Any] = ["workspace": ws, "type": "text", "text_id": long.id, "key": "not a key",
                                         "envelope": try MessageSigner.envelope(long, key: wsKey)]
        XCTAssertEqual(PushCheck.decide(info2, title: "Dev", body: "", me: ph, accepted: [ws: [raw]], nowMs: now).body.count, 120)
    }
}
