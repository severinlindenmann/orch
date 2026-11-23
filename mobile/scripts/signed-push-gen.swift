// Writes three relay-shaped push payloads for scripts/signed-push-check.sh (ORCH-1296), signed now with the fixed
// TEST key below (never a real workspace key; the UI test accepts its public half on the Simulator):
//   signed.json   relay alert text changed, workspace signature intact -> the phone shows the signed words
//   changed.json  the signed text changed after signing                  -> "New message from Pilatus Workspace"
//   unsigned.json no signature at all                                    -> "New message from Pilatus Workspace"
// Built with OrchMobile/MessageSignature.swift only (swiftc, macOS); the signed object is laid out as MessageSigner does.
import CryptoKit
import Foundation

@main
struct SignedPushGen {
    static func main() throws {
        let out = URL(fileURLWithPath: CommandLine.arguments[1])
        let key = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(repeating: 7, count: 32))
        let ws = "ws_pilatus001"
        let body: [String: Any] = ["question_id": "q-backup", "text": "Delete the old backups?", "options": ["yes", "no"],
                                   "recommended": "no"]
        let id = "m_" + String(UUID().uuidString.lowercased().filter(\.isHexDigit).prefix(16))
        let object: [String: Any] = ["v": 1, "id": id, "from": ws, "to": "phones", "type": "question",
                                     "created_ms": Int64(Date().timeIntervalSince1970 * 1000), "origin": "helper", "body": body]
        let bytes = [UInt8](try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]))
        try MessageSignature.checkFields(try MessageSignature.readStrictJSON(bytes))
        let sig = try key.signature(for: Data(MessageSignature.signatureInput(purpose: "msg", signed: bytes)))
        let pub = [UInt8](key.publicKey.rawRepresentation)
        let env: [String: Any] = ["sig_v": 1, "key_id": MessageSignature.keyId(pub), "signed": MessageSignature.b64urlEncode(bytes),
                                  "sig": MessageSignature.b64urlEncode([UInt8](sig))]
        func payload(_ relayText: String, _ envelope: [String: Any]?) -> [String: Any] {
            var p: [String: Any] = ["aps": ["alert": ["title": "Pilatus Workspace", "body": relayText], "sound": "default",
                                            "mutable-content": 1],
                                    "workspace": ws, "message_id": id]
            if let envelope { p["envelope"] = envelope }
            return p
        }
        var changed = env
        var signed = MessageSignature.b64urlDecodeStrict(env["signed"] as! String)!
        let at = signed.firstIndex(of: UInt8(ascii: "D"))!
        signed[at] = UInt8(ascii: "K")
        changed["signed"] = MessageSignature.b64urlEncode(signed)
        for (name, p) in [("signed", payload("Keep the old backups?", env)), ("changed", payload("Keep the old backups?", changed)),
                          ("unsigned", payload("Keep the old backups?", nil))] {
            try JSONSerialization.data(withJSONObject: p, options: [.sortedKeys]).write(to: out.appendingPathComponent("\(name).json"))
        }
        print(MessageSignature.b64urlEncode([UInt8](key.publicKey.rawRepresentation)))
    }
}
