@testable import OrchMobile
import CryptoKit
import XCTest

/// ORCH-1204: the phone's own key and what it signs, checked with the same receiver rules a workspace uses.
final class PhoneSigningTests: XCTestCase {
    private var saved: PhoneKey.Store!

    override func setUp() {
        saved = PhoneKey.store
        PhoneKey.store = .memory()
    }

    override func tearDown() { PhoneKey.store = saved }

    private let ws = "ws_abcdefghij"
    private let ph = "ph_abcdefghij"

    func testNoKeyBeforePairingThenOneKeyKept() throws {
        XCTAssertNil(PhoneKey.current())
        XCTAssertNil(PhoneKey.fingerprint())
        let k = try PhoneKey.makeNew()
        XCTAssertEqual(PhoneKey.current()?.rawRepresentation, k.rawRepresentation)
        let fp = try XCTUnwrap(PhoneKey.fingerprint())
        XCTAssertEqual(fp.split(separator: " ").count, 8)
        XCTAssertEqual(fp, MessageSignature.fingerprint([UInt8](k.publicKey.rawRepresentation)))
        XCTAssertEqual(PhoneKey.publicKeyText(k).count, 43)
        XCTAssertTrue(MessageSignature.publicKeyOK([UInt8](k.publicKey.rawRepresentation)))
    }

    func testANewPairingMakesANewKeyAndSignOutDeletesIt() throws {
        let a = try PhoneKey.makeNew()
        let b = try PhoneKey.makeNew()
        XCTAssertNotEqual(a.publicKey.rawRepresentation, b.publicKey.rawRepresentation)
        XCTAssertEqual(PhoneKey.current()?.rawRepresentation, b.rawRepresentation)
        PhoneKey.delete()
        XCTAssertNil(PhoneKey.current())
    }

    func testKeyThatCannotBeSavedIsAnError() {
        PhoneKey.store = PhoneKey.Store(load: { nil }, save: { _ in false }, delete: {})
        XCTAssertThrowsError(try PhoneKey.makeNew()) { XCTAssertEqual($0 as? PhoneKey.Problem, .notSaved) }
    }

    private func draft(_ body: [String: Any] = ["client_id": "c", "text": "Hallo 👋 \"quoted\" / slash"]) -> MessageSigner.Draft {
        MessageSigner.Draft(from: ph, to: ws, body: body, ticket: "t_abc123", replyTo: "m_aaaaaaaaaaaaaaaa")
    }

    func testWhatThePhoneSignsPassesTheWorkspaceCheck() throws {
        let k = try PhoneKey.makeNew()
        let d = draft()
        let env = try MessageSigner.envelope(d)
        let m = try MessageSignature.receiverCheck(env, me: ws, accepted: [ph: [[UInt8](k.publicKey.rawRepresentation)]],
                                                   nowMs: d.createdMs)
        XCTAssertEqual(m["from"]?.string, ph)
        XCTAssertEqual(m["to"]?.string, ws)
        XCTAssertEqual(m["origin"]?.string, "person")
        XCTAssertEqual(m["type"]?.string, "text")
        XCTAssertEqual(m["id"]?.string, d.id)
        XCTAssertEqual(m["body"]?.object?["text"]?.string, "Hallo 👋 \"quoted\" / slash")
        XCTAssertEqual(m["ticket"]?.string, "t_abc123")
    }

    func testAChangedByteIsRefused() throws {
        let k = try PhoneKey.makeNew()
        var env = try MessageSigner.envelope(draft())
        var signed = MessageSignature.b64urlDecodeStrict(env["signed"] as! String)!
        let i = signed.firstIndex(of: UInt8(ascii: "H"))!
        signed[i] = UInt8(ascii: "J")
        env["signed"] = MessageSignature.b64urlEncode(signed)
        let keys = [ph: [[UInt8](k.publicKey.rawRepresentation)]]
        XCTAssertThrowsError(try MessageSignature.receiverCheck(env, me: ws, accepted: keys, nowMs: MessageSigner.nowMs())) {
            XCTAssertEqual(($0 as? MessageSignature.Refused)?.code, "bad_signature")
        }
    }

    func testAnotherKeyOrAMissingSignatureIsRefused() throws {
        _ = try PhoneKey.makeNew()
        var env = try MessageSigner.envelope(draft())
        let other = Curve25519.Signing.PrivateKey()
        let keys = [ph: [[UInt8](other.publicKey.rawRepresentation)]]
        XCTAssertThrowsError(try MessageSignature.receiverCheck(env, me: ws, accepted: keys, nowMs: MessageSigner.nowMs())) {
            XCTAssertEqual(($0 as? MessageSignature.Refused)?.code, "unknown_key")
        }
        env["sig"] = ""
        XCTAssertThrowsError(try MessageSignature.readEnvelope(env)) {
            XCTAssertEqual(($0 as? MessageSignature.Refused)?.code, "missing_signature")
        }
    }

    func testSigningWithoutAKeyIsAnError() {
        XCTAssertThrowsError(try MessageSigner.envelope(draft())) { XCTAssertEqual($0 as? MessageSigner.Problem, .noKey) }
    }

    func testThePhoneNeverSignsToPhonesOrAGroup() throws {
        _ = try PhoneKey.makeNew()
        let d = MessageSigner.Draft(from: ph, to: "phones", body: ["text": "x"])
        XCTAssertThrowsError(try MessageSigner.envelope(d))
    }

    func testFractionsCannotBeSigned() throws {
        _ = try PhoneKey.makeNew()
        XCTAssertThrowsError(try MessageSigner.envelope(draft(["location": ["lat": 47.1, "lon": 8.5]])))
    }

    func testAnswerNamesTheQuestionHash() throws {
        let wsKey = Curve25519.Signing.PrivateKey()
        let q = MessageSigner.Draft(from: ws, to: ph, type: "question", body: ["text": "OK?"])
        let qEnv = try MessageSigner.envelope(q, key: wsKey)
        let sha = try XCTUnwrap(MessageSigner.questionSha256(envelope: qEnv))
        XCTAssertEqual(sha.count, 64)
        let k = try PhoneKey.makeNew()
        let a = MessageSigner.Draft(from: ph, to: ws, type: "answer", body: ["answer": "yes"], replyTo: q.id,
                                    questionId: q.id, questionSha256: sha)
        let m = try MessageSignature.receiverCheck(try MessageSigner.envelope(a), me: ws,
                                                   accepted: [ph: [[UInt8](k.publicKey.rawRepresentation)]],
                                                   nowMs: a.createdMs)
        XCTAssertEqual(m["question_sha256"]?.string, sha)
    }

}

/// ORCH-1204: a send request is signed with exactly the body the relay builds from it.
final class SendSigningTests: XCTestCase {
    private let ws = "ws_abcdefghij"
    private let ph = "ph_abcdefghij"
    private let cid = "0b0c3f5e-6f3a-4d2b-9c41-2f0a8e7d6c5b"

    private func check(_ e: SignedEnvelope, key: Curve25519.Signing.PrivateKey) throws -> [String: MessageSignature.JSON] {
        let env: [String: Any] = ["sig_v": e.sigV, "key_id": e.keyId, "signed": e.signed, "sig": e.sig]
        return try MessageSignature.receiverCheck(env, me: ws, accepted: [ph: [[UInt8](key.publicKey.rawRepresentation)]],
                                                  nowMs: MessageSigner.nowMs())
    }

    func testATextIsSignedWithTheRelaysBody() throws {
        let k = Curve25519.Signing.PrivateKey()
        let r = SendRequest(to: ws, clientId: cid, text: "Bitte prüfen", ticket: "t_abc123", general: nil, replyTo: "m_aaaaaaaaaaaaaaaa")
        let e = try XCTUnwrap(MessageSigner.sign(r, phoneId: ph, key: k) { _ in nil })
        let m = try check(e, key: k)
        XCTAssertEqual(m["body"], .object(["client_id": .string(cid), "text": .string("Bitte prüfen")]))
        XCTAssertEqual(m["ticket"]?.string, "t_abc123")
        XCTAssertEqual(m["reply_to"]?.string, "m_aaaaaaaaaaaaaaaa")
        XCTAssertNil(m["files"])
        // On the wire the envelope sits next to today's fields.
        var wire = r
        wire.envelope = e
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(wire)) as? [String: Any])
        let env = try XCTUnwrap(json["envelope"] as? [String: Any])
        XCTAssertEqual(Set(env.keys), ["sig_v", "key_id", "signed", "sig"])
    }

    func testFilesAreSignedBySizeAndHash() throws {
        let k = Curve25519.Signing.PrivateKey()
        var r = SendRequest(to: ws, clientId: cid, text: "Photo")
        r.attachments = [MessageAttachment(blobId: "b_0123456789abcdef", kind: .image, name: "a.jpg", size: 3, mime: "image/jpeg")]
        let sha = String(repeating: "a", count: 64)
        let e = try XCTUnwrap(MessageSigner.sign(r, phoneId: ph, key: k) { $0 == "b_0123456789abcdef" ? (3, sha) : nil })
        let m = try check(e, key: k)
        XCTAssertEqual(m["files"], .array([.object(["blob_id": .string("b_0123456789abcdef"), "size": .int(3), "sha256": .string(sha)])]))
        XCTAssertNil(MessageSigner.sign(r, phoneId: ph, key: k) { _ in nil }, "a file without its local copy is not signed")
    }

    func testALocationWithFractionsGoesUnsigned() {
        var r = SendRequest(to: ws, clientId: cid)
        r.location = LocationShare(lat: 47.37, lon: 8.54)
        XCTAssertNil(MessageSigner.sign(r, phoneId: ph, key: Curve25519.Signing.PrivateKey()) { _ in nil })
    }

    /// ORCH-1204 c9: an answer to a signed question is signed with the body the relay builds and names the question.
    func testAnAnswerIsSignedWithTheRelaysBodyAndTheQuestionHash() throws {
        let wsKey = Curve25519.Signing.PrivateKey()
        let q = MessageSigner.Draft(from: ws, to: "phones", type: "question", body: ["question_id": "q1", "text": "OK?"], ticket: "t_abc123")
        let qEnv = try MessageSigner.envelope(q, key: wsKey)
        let sha = try XCTUnwrap(MessageSigner.questionSha256(envelope: qEnv))
        let k = Curve25519.Signing.PrivateKey()
        let r = AnswerRequest(questionMessageId: q.id, answer: "yes", clientId: cid)
        let e = try XCTUnwrap(MessageSigner.signAnswer(r, to: ws, ticket: "t_abc123", questionId: "q1", questionEnvelope: qEnv,
                                                       phoneId: ph, key: k) { _ in nil })
        let m = try check(e, key: k)
        XCTAssertEqual(m["type"]?.string, "answer")
        XCTAssertEqual(m["body"], .object(["question_id": .string("q1"), "answer": .string("yes"),
                                           "answered_by": .string("human:\(ph)"), "client_id": .string(cid)]))
        XCTAssertEqual(m["reply_to"]?.string, q.id)
        XCTAssertEqual(m["ticket"]?.string, "t_abc123")
        XCTAssertEqual(m["question_id"]?.string, "q1")
        XCTAssertEqual(m["question_sha256"]?.string, sha)
        // On the wire the envelope sits next to today's answer fields.
        var wire = r
        wire.envelope = e
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(wire)) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["question_message_id", "answer", "client_id", "envelope"])
    }

    func testAnAnswerToAnUnreadableQuestionEnvelopeGoesUnsigned() {
        let r = AnswerRequest(questionMessageId: "m_aaaaaaaaaaaaaaaa", answer: "yes", clientId: cid)
        XCTAssertNil(MessageSigner.signAnswer(r, to: ws, ticket: nil, questionId: "q1", questionEnvelope: ["sig_v": 1],
                                              phoneId: ph, key: Curve25519.Signing.PrivateKey()) { _ in nil })
    }

    func testAnOutboxAnswerKeepsWhatItsSignatureNeeds() throws {
        let env = SignedEnvelope(sigV: 1, keyId: "0123456789abcdef", signed: "e30", sig: String(repeating: "A", count: 86))
        var msg = QuestionMessage(schema: "orch.msg/1", id: "m_aaaaaaaaaaaaaaaa", from: ws, to: "phones", type: "question",
                                  createdAt: "2026-11-26T10:00:00Z", ticket: "t_abc123",
                                  body: QuestionBody(questionId: "q1", title: "T", text: "OK?", options: ["yes", "no"], recommended: nil))
        msg.envelope = env
        var item = OutboxItem(clientId: cid, phone: ph, kind: .answer, workspace: ws, createdAt: "2026-11-26T10:00:00Z")
        Outbox.remember(Question(message: msg, workspaceName: "Dev"), in: &item)
        XCTAssertEqual(item.questionEnvelope, env)
        XCTAssertEqual(item.questionId, "q1")
        XCTAssertEqual(item.questionTicket, "t_abc123")
        let back = try JSONCoding.decoder.decode(OutboxItem.self, from: JSONCoding.encoder.encode(item))
        XCTAssertEqual(back, item, "kept across a restart, so a retry signs the same")
    }

    func testLocalFileFacts() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("facts-\(UUID().uuidString)")
        try Data("abc".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let f = try XCTUnwrap(MessageSigner.facts(of: url))
        XCTAssertEqual(f.size, 3)
        XCTAssertEqual(f.sha256, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }
}

/// Pairing sends the phone's own public key; signing out deletes the key (real keychain of the simulator).
@MainActor
final class PhonePairingKeyTests: XCTestCase {
    override func setUp() async throws { Keychain.delete(); PhoneKey.delete() }
    override func tearDown() async throws { Keychain.delete(); PhoneKey.delete() }

    func testPairingRegistersThisPhonesKeyAndSignOutDeletesIt() async throws {
        let model = AppModel(useMock: true)
        model.openSampleInvite()
        await model.connect(phoneName: "Test phone")
        let sent = await model.mock?.pairedPublicKey
        let key = try XCTUnwrap(PhoneKey.current(), "the key is in the keychain after pairing")
        XCTAssertEqual(sent, PhoneKey.publicKeyText(key))
        XCTAssertNotNil(PhoneKey.fingerprint())
        await model.signOut()
        XCTAssertNil(PhoneKey.current())
    }
}

/// Choice G: Face ID (or the phone's code) before an allow answer; other answers never ask.
@MainActor
final class AllowNeedsThePersonTests: XCTestCase {
    override func setUp() async throws { Keychain.delete(); PhoneKey.delete(); UserDefaults.standard.removeObject(forKey: "chatOutbox"); UserDefaults.standard.set(true, forKey: "mockFail") }
    override func tearDown() async throws { Keychain.delete(); PhoneKey.delete(); UserDefaults.standard.removeObject(forKey: "chatOutbox"); UserDefaults.standard.removeObject(forKey: "mockFail") }

    private final class Count: @unchecked Sendable { var n = 0 }

    private func paired(_ check: PersonCheck) async -> AppModel {
        let model = AppModel(useMock: true)
        model.openSampleInvite(); await model.connect(phoneName: "Test phone"); await model.finishSetup(allowNotifications: false)
        model.personCheck = check
        return model
    }

    func testARefusedCheckSendsNothing() async {
        let model = await paired(.never)
        let q = MockRelay.allowQuestion
        await model.answer(q, with: q.message.body.options[0])
        XCTAssertFalse(model.outbox.items.contains { $0.kind == .answer })
        XCTAssertEqual(model.announcement, "Not sent. Confirm it is you to allow this.")
    }

    func testAPassedCheckSendsTheAllow() async {
        let asked = Count()
        let model = await paired(PersonCheck { _ in asked.n += 1; return true })
        let q = MockRelay.allowQuestion
        await model.answer(q, with: q.message.body.options[0])
        XCTAssertEqual(asked.n, 1)
        XCTAssertTrue(model.outbox.items.contains { $0.kind == .answer && $0.questionMessageId == q.id })
    }

    func testANormalAnswerNeverAsks() async {
        let asked = Count()
        let model = await paired(PersonCheck { _ in asked.n += 1; return false })
        let q = MockRelayTestsFixtures.question
        await model.answer(q, with: q.message.body.options[0])
        XCTAssertEqual(asked.n, 0)
        XCTAssertTrue(model.outbox.items.contains { $0.kind == .answer })
    }
}
