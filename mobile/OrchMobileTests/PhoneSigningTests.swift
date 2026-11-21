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
