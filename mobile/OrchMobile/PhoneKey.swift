import CryptoKit
import Foundation
import Security

/// The phone's own signing key (ORCH-1204, design ORCH-1027 section 2): Ed25519 from CryptoKit, kept as one
/// keychain item for this device only and readable only while the phone is unlocked. It never leaves the phone:
/// only the raw public key goes to the relay at pairing. A new pairing makes a new key (a new contact for the
/// workspaces); signing out deletes it.
enum PhoneKey {
    private static let service = "io.severin.orch.mobile"
    private static let account = "signing-key-v1"

    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    /// Tests and previews swap the keychain for memory.
    nonisolated(unsafe) static var store: Store = .keychain

    struct Store: Sendable {
        let load: @Sendable () -> Data?
        let save: @Sendable (Data) -> Bool
        let delete: @Sendable () -> Void

        static let keychain = Store(
            load: {
                var q = PhoneKey.query
                q[kSecReturnData as String] = true
                q[kSecMatchLimit as String] = kSecMatchLimitOne
                var out: AnyObject?
                guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess else { return nil }
                return out as? Data
            },
            save: { data in
                SecItemDelete(PhoneKey.query as CFDictionary)
                var q = PhoneKey.query
                q[kSecValueData as String] = data
                q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
                q[kSecAttrSynchronizable as String] = false
                return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
            },
            delete: { SecItemDelete(PhoneKey.query as CFDictionary) }
        )

        static func memory() -> Store {
            let box = Box()
            return Store(load: { box.data }, save: { box.data = $0; return true }, delete: { box.data = nil })
        }

        private final class Box: @unchecked Sendable { var data: Data? }
    }

    enum Problem: Error, Equatable { case notSaved, missing }

    /// The key of this phone, or nil before pairing (or while the phone is locked).
    static func current() -> Curve25519.Signing.PrivateKey? {
        guard let raw = store.load(), raw.count == 32 else { return nil }
        return try? Curve25519.Signing.PrivateKey(rawRepresentation: raw)
    }

    /// A fresh key for a new pairing; replaces any old one. CryptoKit never makes a weak public key, but the
    /// shared key rule is checked anyway so the relay can never refuse it.
    @discardableResult
    static func makeNew() throws -> Curve25519.Signing.PrivateKey {
        var key = Curve25519.Signing.PrivateKey()
        while !MessageSignature.publicKeyOK([UInt8](key.publicKey.rawRepresentation)) {
            key = Curve25519.Signing.PrivateKey()
        }
        guard store.save(key.rawRepresentation) else { throw Problem.notSaved }
        return key
    }

    static func delete() { store.delete() }

    /// Raw 32 bytes in base64url without padding, as the relay takes it (`public_key`).
    static func publicKeyText(_ key: Curve25519.Signing.PrivateKey) -> String {
        MessageSignature.b64urlEncode([UInt8](key.publicKey.rawRepresentation))
    }

    /// This phone's fingerprint, always computed from its own key (never read from the relay).
    static func fingerprint() -> String? {
        current().map { MessageSignature.fingerprint([UInt8]($0.publicKey.rawRepresentation)) }
    }
}
