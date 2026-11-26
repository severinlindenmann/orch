import Foundation
import Security

/// What a credential lookup found. `unavailable` is a read that failed (the phone is still locked after a restart, the
/// keychain is busy): the pairing may well be there, so nothing that belongs to it may be wiped on that answer.
enum CredentialRead: Equatable {
    case found(Credentials)
    case missing
    case unavailable(OSStatus)

    var credentials: Credentials? { if case .found(let c) = self { return c } else { return nil } }
    var isUnavailable: Bool { if case .unavailable = self { return true } else { return false } }
}

/// Where the app keeps its credentials. The Keychain in the app; tests inject a fake to replay read and write failures.
protocol CredentialStore {
    func read() -> CredentialRead
    /// False when the credentials were not stored: the caller must not act as if they were.
    func save(_ c: Credentials) -> Bool
    func delete()
}

struct KeychainCredentials: CredentialStore {
    func read() -> CredentialRead { Keychain.read() }
    func save(_ c: Credentials) -> Bool { Keychain.save(c) }
    func delete() { Keychain.delete() }
}

/// Token and phone id live in the Keychain, nothing else is stored.
enum Keychain {
    private static let service = "io.severin.orch.mobile"
    private static let account = "credentials"

    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    static func load() -> Credentials? { read().credentials }

    /// Only "no such item" counts as missing; any other failed lookup is `unavailable`. A stored item that does not
    /// decode stays unreadable on every try, so it counts as missing.
    static func read() -> CredentialRead {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { return .missing }
        guard status == errSecSuccess else { return .unavailable(status) }
        guard let data = out as? Data, let c = try? JSONDecoder().decode(Credentials.self, from: data) else { return .missing }
        return .found(c)
    }

    /// Updates in place, so a failed write never leaves the phone without its token. This device only: never in a
    /// backup or iCloud Keychain; readable after the first unlock so a refresh in the background works.
    @discardableResult
    static func save(_ c: Credentials) -> Bool {
        guard let data = try? JSONEncoder().encode(c) else { return false }
        let attributes: [String: Any] = [kSecValueData as String: data,
                                         kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let updated = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updated == errSecSuccess { return true }
        guard updated == errSecItemNotFound else { return false }
        return SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess
    }

    /// How the stored item may be read (`kSecAttrAccessible…`); nil when nothing is stored.
    static func accessibility() -> String? {
        var q = query
        q[kSecReturnAttributes as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let a = out as? [String: Any] else { return nil }
        return a[kSecAttrAccessible as String] as? String
    }

    static func delete() { SecItemDelete(query as CFDictionary) }
}
