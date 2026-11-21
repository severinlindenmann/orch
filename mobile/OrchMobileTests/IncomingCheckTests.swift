@testable import OrchMobile
import CryptoKit
import XCTest

/// ORCH-1204: the phone checks what a workspace sends and refuses a changed message; Accept once per workspace.
final class IncomingCheckTests: XCTestCase {
    private let ws = "ws_abcdefghij"
    private let ph = "ph_abcdefghij"
    private let wsKey = Curve25519.Signing.PrivateKey()
    private var raw: [UInt8] { [UInt8](wsKey.publicKey.rawRepresentation) }
    private var keyText: String { MessageSignature.b64urlEncode(raw) }

    /// A text the workspace signed, as the relay hands it to the phone; `relayText` lets the relay change its copy.
    private func message(_ text: String = "Build is green", relayText: String? = nil, key: Curve25519.Signing.PrivateKey? = nil) throws -> TextMessage {
        let d = MessageSigner.Draft(from: ws, to: ph, body: ["text": text], ticket: "t_abc123")
        let e = try MessageSigner.envelope(d, key: key ?? wsKey)
        let outer: [String: Any] = ["id": d.id, "from": ws, "to": ph, "type": "text", "created_at": "2026-11-21T10:00:00Z",
                                    "ticket": "t_abc123", "body": ["text": relayText ?? text], "envelope": e]
        return try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: outer))
    }

    func testAcceptedAndUnchangedIsShown() throws {
        let m = try message()
        XCTAssertNotNil(m.envelope)
        XCTAssertEqual(IncomingCheck.check(m, me: ph, accepted: [ws: [raw]], hints: [ws: raw]), .ok)
    }

    func testTextTheRelayChangedShowsWhatTheWorkspaceSigned() throws {
        let m = try message("Do not deploy", relayText: "Deploy now")
        let (v, shown) = IncomingCheck.shown(m, me: ph, accepted: [ws: [raw]], hints: [:])
        XCTAssertEqual(v, .ok)
        XCTAssertEqual(shown?.body.text, "Do not deploy", "rebuilt from the signed bytes, not the relay's JSON (ORCH-1296)")
        XCTAssertEqual(shown?.ticket, "t_abc123")
    }

    func testChangedSignedBytesAreRefused() throws {
        var m = try message()
        let e = try XCTUnwrap(m.envelope)
        var signed = try XCTUnwrap(MessageSignature.b64urlDecodeStrict(e.signed))
        signed[signed.firstIndex(of: UInt8(ascii: "B"))!] = UInt8(ascii: "G")
        m.envelope = SignedEnvelope(sigV: 1, keyId: e.keyId, signed: MessageSignature.b64urlEncode(signed), sig: e.sig)
        XCTAssertEqual(IncomingCheck.check(m, me: ph, accepted: [ws: [raw]], hints: [ws: raw]), .refused("bad_signature"))
    }

    func testNotAcceptedYetIsHeldAndAForgeryIsRefused() throws {
        let m = try message()
        XCTAssertEqual(IncomingCheck.check(m, me: ph, accepted: [:], hints: [ws: raw]), .held)
        let forged = try message(key: Curve25519.Signing.PrivateKey())
        XCTAssertEqual(IncomingCheck.check(forged, me: ph, accepted: [:], hints: [ws: raw]), .refused("unknown_key"))
        XCTAssertEqual(IncomingCheck.check(forged, me: ph, accepted: [ws: [raw]], hints: [ws: raw]), .refused("unknown_key"))
    }

    func testUnsignedStaysUnsigned() throws {
        var m = try message()
        m.envelope = nil
        XCTAssertEqual(IncomingCheck.check(m, me: ph, accepted: [:], hints: [ws: raw]), .unsigned, "until the hard cut")
        XCTAssertEqual(IncomingCheck.check(m, me: ph, accepted: [ws: [raw]], hints: [:]), .refused("missing_signature"),
                       "an accepted workspace's message without its signature is refused")
    }

    func testAcceptOnceThenAcceptedAndAChangedKeyAsksAgain() throws {
        let store = TrustStore.memory()
        let w = Workspace(id: ws, name: "W", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0,
                          signingKey: WorkspaceKey(alg: "ed25519", publicKey: keyText, keyId: MessageSignature.keyId(raw)))
        XCTAssertEqual(IncomingCheck.senderState(w, accepted: store.accepted()), .notAcceptedYet)
        XCTAssertTrue(store.accept(ws, key: keyText))
        XCTAssertEqual(IncomingCheck.senderState(w, accepted: store.accepted()), .accepted)
        XCTAssertEqual(IncomingCheck.check(try message(), me: ph, accepted: store.accepted(), hints: [:]), .ok)
        var moved = w
        let newRaw = [UInt8](Curve25519.Signing.PrivateKey().publicKey.rawRepresentation)
        moved.signingKey = WorkspaceKey(alg: "ed25519", publicKey: MessageSignature.b64urlEncode(newRaw), keyId: MessageSignature.keyId(newRaw))
        XCTAssertEqual(IncomingCheck.senderState(moved, accepted: store.accepted()), .changed)
        store.withdraw(ws)
        XCTAssertEqual(IncomingCheck.senderState(w, accepted: store.accepted()), .notAcceptedYet)
    }

    func testAWeakKeyIsNeverAccepted() {
        let store = TrustStore.memory()
        XCTAssertFalse(store.accept(ws, key: MessageSignature.b64urlEncode([UInt8](repeating: 0, count: 32))))
        XCTAssertTrue(store.accepted().isEmpty)
    }

    func testTheKeychainStoreKeepsWhatWasAccepted() {
        let store = TrustStore.keychain
        store.clear()
        defer { store.clear() }
        XCTAssertTrue(store.accept(ws, key: keyText))
        XCTAssertEqual(TrustStore.keychain.accepted()[ws], [raw])
    }
}

/// The phone holds a workspace's messages until the person accepts it, then shows them; a changed one never shows.
@MainActor
final class AcceptOnPhoneTests: XCTestCase {
    func testHeldUntilAcceptThenShownAndChangedNeverShown() async throws {
        let model = AppModel(useMock: true)
        let wsKey = Curve25519.Signing.PrivateKey()
        let raw = [UInt8](wsKey.publicKey.rawRepresentation)
        let ws = "ws_abcdefghij"
        model.testSetWorkspaces([Workspace(id: ws, name: "Dev", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0,
                                           signingKey: WorkspaceKey(alg: "ed25519", publicKey: MessageSignature.b64urlEncode(raw), keyId: MessageSignature.keyId(raw)))])
        func incoming(_ text: String, relayText: String? = nil) throws -> PhoneMessage {
            let d = MessageSigner.Draft(from: ws, to: "phones", body: ["text": text])
            let e = try MessageSigner.envelope(d, key: wsKey)
            let outer: [String: Any] = ["message": ["id": d.id, "from": ws, "to": "phones", "type": "text", "created_at": "2026-11-21T10:00:00Z",
                                                    "body": ["text": relayText ?? text], "envelope": e], "workspace_name": "Dev"]
            return try JSONCoding.decoder.decode(PhoneMessage.self, from: JSONSerialization.data(withJSONObject: outer))
        }
        XCTAssertEqual(model.senderState(ws), .notAcceptedYet)
        XCTAssertEqual(model.fingerprint(of: ws), MessageSignature.fingerprint(raw))
        let good = try incoming("Hello")
        let changed = try incoming("Stop", relayText: "Go")
        var forged = try incoming("Pay now")
        forged = PhoneMessage(message: { var m = forged.message; m.envelope = SignedEnvelope(sigV: 1, keyId: m.envelope!.keyId, signed: m.envelope!.signed,
                                                                                            sig: MessageSignature.b64urlEncode([UInt8](repeating: 1, count: 64))); return m }(),
                              workspaceName: "Dev")
        model.testMerge([good, changed, forged])
        XCTAssertFalse(model.messages.contains { $0.id == good.id }, "held before Accept")
        XCTAssertEqual(model.held[ws]?.map(\.id), [good.id, changed.id])
        XCTAssertEqual(model.notValid[ws], [forged.id])
        XCTAssertFalse(model.acceptWorkspace(ws, shownFingerprint: "0000 0000 0000 0000 0000 0000 0000 0000"),
                       "a fingerprint other than the listed key accepts nothing")
        XCTAssertEqual(model.senderState(ws), .notAcceptedYet)
        XCTAssertTrue(model.acceptWorkspace(ws, shownFingerprint: MessageSignature.fingerprint(raw)))
        XCTAssertEqual(model.senderState(ws), .accepted)
        XCTAssertTrue(model.messages.contains { $0.id == good.id }, "shown after Accept")
        XCTAssertEqual(model.messages.first { $0.id == changed.id }?.message.body.text, "Stop",
                       "the chat shows what the workspace signed, not the relay's changed copy (ORCH-1296)")
        XCTAssertFalse(model.messages.contains { $0.id == forged.id })
        model.testMerge([good])
        XCTAssertNil(model.held[ws], "accepted once: not held again")
        // A message that claims to come from another phone is never shown.
        let other: [String: Any] = ["message": ["id": "m_otherphone000001", "from": "ph_zzzzzzzzzz", "to": ws, "type": "text",
                                                "created_at": "2026-11-21T10:00:00Z", "body": ["text": "hi"]], "workspace_name": "Dev"]
        let fake = try JSONCoding.decoder.decode(PhoneMessage.self, from: JSONSerialization.data(withJSONObject: other))
        model.testMerge([fake])
        XCTAssertFalse(model.messages.contains { $0.id == fake.id })
    }
}
