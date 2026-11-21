@testable import OrchMobile
import CryptoKit
import XCTest

/// Signed messages v1: the shared vectors (contracts/vectors/msgsig-v1.json, copied to Fixtures) on the phone.
final class MessageSignatureTests: XCTestCase {
    private final class Token {}

    private func vectors() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle(for: Token.self).url(forResource: "msgsig-v1", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }

    private func hex(_ s: Any?) -> [UInt8] { MessageSignature.hexBytes(s as! String) }

    func testConstantsMatchTheContract() throws {
        let c = try vectors()["constants"] as! [String: Any]
        XCTAssertEqual(c["tag"] as? String, "orch-sig-v1")
        XCTAssertEqual(c["purposes"] as? [String], MessageSignature.purposes)
        XCTAssertEqual(c["max_signed_bytes"] as? Int, MessageSignature.maxSignedBytes)
        XCTAssertEqual(c["max_depth"] as? Int, MessageSignature.maxDepth)
        XCTAssertEqual((c["future_skew_ms"] as? NSNumber)?.int64Value, MessageSignature.futureSkewMs)
        XCTAssertEqual((c["max_expiry_ms"] as? NSNumber)?.int64Value, MessageSignature.maxExpiryMs)
        XCTAssertEqual((c["max_age_ms"] as? NSNumber)?.int64Value, MessageSignature.maxAgeMs)
    }

    func testKeyIdsAndFingerprints() throws {
        for (name, p) in try vectors()["parties"] as! [String: [String: Any]] {
            let pub = hex(p["pub"])
            let sk = try Curve25519.Signing.PrivateKey(rawRepresentation: hex(p["seed"]))
            XCTAssertEqual([UInt8](sk.publicKey.rawRepresentation), pub, name)
            XCTAssertEqual(MessageSignature.keyId(pub), p["key_id"] as? String, name)
            XCTAssertEqual(MessageSignature.fingerprint(pub), p["fingerprint"] as? String, name)
        }
    }

    func testPublicKeyRules() throws {
        for c in try vectors()["keys"] as! [[String: Any]] {
            XCTAssertEqual(MessageSignature.publicKeyOK(hex(c["pub"])), c["ok"] as? Bool, c["name"] as! String)
        }
    }

    /// CryptoKit signs with randomness, so the phone checks that the vector signatures verify, and that its own
    /// signature over the same bytes verifies too (round trip).
    func testSignaturesVerifyAndRoundTrip() throws {
        for c in try vectors()["sign"] as! [[String: Any]] {
            let name = c["name"] as! String
            let signed = try XCTUnwrap(MessageSignature.b64urlDecodeStrict(c["signed"] as! String))
            let sig = try XCTUnwrap(MessageSignature.b64urlDecodeStrict(c["sig"] as! String))
            let sk = try Curve25519.Signing.PrivateKey(rawRepresentation: hex(c["seed"]))
            let pub = [UInt8](sk.publicKey.rawRepresentation)
            let input = MessageSignature.signatureInput(purpose: c["purpose"] as! String, signed: signed)
            XCTAssertTrue(MessageSignature.verifyRaw(pub: pub, data: input, sig: sig), name)
            let mine = try [UInt8](sk.signature(for: Data(input)))
            XCTAssertTrue(MessageSignature.verifyRaw(pub: pub, data: input, sig: mine), name)
        }
    }

    func testStrictJSON() throws {
        for c in try vectors()["strict_json"] as! [[String: Any]] {
            let ok = (try? MessageSignature.readStrictJSON(hex(c["hex"]))) != nil
            XCTAssertEqual(ok, c["ok"] as? Bool, c["name"] as! String)
        }
    }

    func testReceiver() throws {
        var n = 0
        for c in try vectors()["messages"] as! [[String: Any]] {
            guard let rx = c["receiver"] as? [String: Any] else { continue }
            let accepted = (rx["accepted"] as! [String: [String]]).mapValues { $0.map { MessageSignature.hexBytes($0) } }
            let seen = Set((rx["seen"] as! [[String]]))
            let groups = Set((rx["groups"] as! [[String]]))
            let got: String
            do {
                _ = try MessageSignature.receiverCheck(c["envelope"], me: rx["me"] as! String, accepted: accepted,
                                                       nowMs: (rx["now_ms"] as! NSNumber).int64Value,
                                                       seen: seen, groups: groups)
                got = "ok"
            } catch let e as MessageSignature.Refused {
                got = e.code
            }
            XCTAssertEqual(got, c["expect_receiver"] as? String, "\(c["name"]!): \(c["note"]!)")
            n += 1
        }
        XCTAssertGreaterThanOrEqual(n, 60)
    }

    func testWycheproof() throws {
        let w = try vectors()["wycheproof"] as! [String: Any]
        var wrong: [String] = []
        for t in w["cases"] as! [[String: Any]] {
            guard let exp = t["expect"] as? Bool else { continue }  // "either": mixed-order keys, never registered
            let got = MessageSignature.verifyRaw(pub: hex(t["pk"]), data: hex(t["msg"]), sig: hex(t["sig"]))
            if got != exp { wrong.append("tc \(t["tcId"]!) \(t["flags"]!) expected \(exp)") }
        }
        XCTAssertEqual(wrong, [])
    }
}
