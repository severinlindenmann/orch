import Foundation
import UserNotifications

/// Checks a workspace's push before it is shown (ORCH-1296, design ORCH-1198 section 7). The relay writes push
/// text; only text the workspace signed with the key the person accepted on this phone is shown. Anything else
/// shows "New message from <workspace>" with no answer button. The keys and the phone id come from the keychain
/// group this extension shares with the app (TrustStore); nothing here talks to the network.
final class NotificationService: UNNotificationServiceExtension {
    private var handler: ((UNNotificationContent) -> Void)?
    private var fallback: UNMutableNotificationContent?

    override func didReceive(_ request: UNNotificationRequest, withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void) {
        guard let content = request.content.mutableCopy() as? UNMutableNotificationContent else {
            contentHandler(request.content)
            return
        }
        handler = contentHandler
        let safe = Self.generic(content)
        fallback = safe
        let shown = PushCheck.decide(content.userInfo, title: content.title, body: content.body, me: TrustStore.phoneId(),
                                     accepted: TrustStore.keychain.accepted(), nowMs: Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)))
        if shown.verified {
            content.body = shown.body
            contentHandler(content)
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

    private static func generic(_ c: UNMutableNotificationContent) -> UNMutableNotificationContent {
        guard let g = c.mutableCopy() as? UNMutableNotificationContent else { return c }
        g.body = PushCheck.generic(c.title)
        g.subtitle = ""
        g.categoryIdentifier = ""   // no answer button unless the question was checked
        g.attachments = []
        return g
    }
}
