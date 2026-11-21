import Foundation
import OSLog
import UserNotifications

/// Checks a workspace's push before it is shown (ORCH-1296, design ORCH-1198 section 7). The relay writes push
/// text; only text the workspace signed with the key the person accepted on this phone is shown. Anything else
/// shows "New message from <workspace>" with no answer button. The keys and the phone id come from the keychain
/// group this extension shares with the app (TrustStore); nothing here talks to the network.
final class NotificationService: UNNotificationServiceExtension {
    private static let log = Logger(subsystem: "io.severin.orch", category: "push-check")
    private var handler: ((UNNotificationContent) -> Void)?
    private var fallback: UNMutableNotificationContent?

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        guard let content = request.content.mutableCopy() as? UNMutableNotificationContent else {
            contentHandler(request.content)
            return
        }
        handler = contentHandler
        // Until the check is done, running out of time shows only the plain notice with a short name.
        fallback = Self.generic(content, name: String(content.title.prefix(PushCheck.maxNameChars)))
        let store = TrustStore.keychain
        let shown = PushCheck.decide(content.userInfo, title: content.title, body: content.body, me: TrustStore.phoneId(),
                                     accepted: store.accepted(), names: store.names(),
                                     nowMs: Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)))
        let safe = Self.generic(content, name: shown.title)
        // Only whether it checked out and whether keys were there: never the text or a key.
        Self.log.info("push check verified=\(shown.verified, privacy: .public) accepted=\(store.accepted().count, privacy: .public) phone=\(TrustStore.phoneId() != nil, privacy: .public)")
        if shown.verified, let checked = safe.mutableCopy() as? UNMutableNotificationContent {
            // Built from the plain copy: only the signed words and the name saved at Accept; nothing else the relay set.
            checked.body = shown.body
            contentHandler(checked)
        } else {
            contentHandler(safe)
        }
        handler = nil
    }

    /// Out of time: never the relay's own words.
    override func serviceExtensionTimeWillExpire() {
        if let handler, let fallback { handler(fallback) }
        handler = nil
    }

    private static func generic(_ c: UNMutableNotificationContent, name: String) -> UNMutableNotificationContent {
        guard let g = c.mutableCopy() as? UNMutableNotificationContent else { return c }
        g.title = name
        g.body = PushCheck.generic(name)
        g.subtitle = ""
        g.categoryIdentifier = ""   // no answer button unless the question was checked
        g.attachments = []
        return g
    }
}
