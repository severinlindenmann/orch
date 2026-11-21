import Foundation
import Security

/// The phone's own list of accepted workspaces (ORCH-1204, design ORCH-1027 section 5): the full public key a person
/// accepted for each workspace, kept in the keychain for this device only, never from the relay. Accept is a
/// person's tap in that workspace's chat; withdrawing is always possible.
///
/// The list and this phone's id live in a keychain group the notification extension shares (ORCH-1296), so the
/// extension can check a push before it shows the text. Nothing secret is in it: public keys and the phone id.
/// The app's token and private key stay in the app's own group.
struct TrustStore: Sendable {
    struct Entry: Codable, Sendable, Equatable {
        let publicKey: String     // base64url raw key
        let acceptedAt: String
    }

    let load: @Sendable () -> [String: Entry]
    let save: @Sendable ([String: Entry]) -> Void

    /// The keychain group the app and the notification extension share (both entitlements list it).
    static let sharedGroupSuffix = "io.severin.orch.shared"
    private static let service = "io.severin.orch.mobile"
    private static let account = "trust-v1"
    private static let phoneAccount = "phone-id-v1"

    /// `<team prefix>.io.severin.orch.shared`, read from the bundle's `AppIdentifierPrefix` Info.plist key;
    /// nil when the build has none (unit tests on a plain host): the item then stays in the default group.
    static var sharedGroup: String? {
        guard let p = Bundle.main.object(forInfoDictionaryKey: "AppIdentifierPrefix") as? String, !p.isEmpty else { return nil }
        return p + sharedGroupSuffix
    }

    private static func query(_ account: String) -> [String: Any] {
        var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account]
        if let g = sharedGroup { q[kSecAttrAccessGroup as String] = g }
        return q
    }

    private static func read(_ account: String) -> Data? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    private static func write(_ account: String, _ data: Data?) {
        SecItemDelete(query(account) as CFDictionary)
        guard let data else { return }
        var q = query(account)
        q[kSecValueData as String] = data
        // The extension runs on a locked phone too: readable after the first unlock, never leaves this device.
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(q as CFDictionary, nil)
    }

    static let keychain = TrustStore(
        load: {
            guard let d = TrustStore.read(TrustStore.account), let m = try? JSONDecoder().decode([String: Entry].self, from: d) else { return [:] }
            return m
        },
        save: { m in
            TrustStore.write(TrustStore.account, m.isEmpty ? nil : try? JSONEncoder().encode(m))
        }
    )

    /// This phone's id, for the extension's "is it for me" check. Written when the phone pairs or starts paired.
    static func savePhoneId(_ id: String?) { write(phoneAccount, id.flatMap { $0.data(using: .utf8) }) }
    static func phoneId() -> String? { read(phoneAccount).flatMap { String(data: $0, encoding: .utf8) } }

    static func memory() -> TrustStore {
        final class Box: @unchecked Sendable { var m: [String: Entry] = [:] }
        let b = Box()
        return TrustStore(load: { b.m }, save: { b.m = $0 })
    }

    /// Raw accepted keys per workspace, for `MessageSignature.receiverCheck`.
    func accepted() -> [String: [[UInt8]]] {
        load().compactMapValues { e in MessageSignature.b64urlDecodeStrict(e.publicKey).map { [$0] } }
    }

    /// Accept `key` for `workspace` (the person's tap). A weak or malformed key is never accepted.
    @discardableResult
    func accept(_ workspace: String, key: String, now: Date = Date()) -> Bool {
        guard let raw = MessageSignature.b64urlDecodeStrict(key), MessageSignature.publicKeyOK(raw) else { return false }
        var m = load()
        m[workspace] = Entry(publicKey: key, acceptedAt: ISO8601DateFormatter().string(from: now))
        save(m)
        return true
    }

    func withdraw(_ workspace: String) {
        var m = load()
        m[workspace] = nil
        save(m)
    }

    func clear() { save([:]) }
}
