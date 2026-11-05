import SwiftUI
import UIKit
import UserNotifications

/// Push: `{"aps": {...}, "message_id": "m_…", "workspace": "ws_…"}`. Tapping opens that question.
@MainActor
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NSLog("orch push registration failed: \(error.localizedDescription)")
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { await AppDelegate.model?.registerPush(token: hex) }
    }

    /// Tapped banner. Completion-handler form on purpose: the async form crashed (SIGABRT) when the app was in the background.
    /// UIKit calls this on the main thread; the handler is called exactly once, after the UI state is updated.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping @Sendable () -> Void) {
        let id = PushPayload.messageId(response.notification.request.content.userInfo)
        DispatchQueue.main.async {
            AppDelegate.handleTap(messageId: id)
            completionHandler()
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping @Sendable (UNNotificationPresentationOptions) -> Void) {
        DispatchQueue.main.async {
            if let model = AppDelegate.model { Task { await model.refresh() } }
            completionHandler([.banner, .sound])
        }
    }

    /// A tap that arrives before the model exists (app launched from terminated by the tap) waits here.
    static var pendingQuestion: String?
    static weak var model: AppModel? {
        didSet {
            if let m = model, let id = pendingQuestion { pendingQuestion = nil; m.openQuestion(messageId: id) }
        }
    }

    @MainActor static func handleTap(messageId: String?) {
        guard let messageId else { return }
        if let model { model.openQuestion(messageId: messageId) } else { pendingQuestion = messageId }
    }
}

enum PushPayload {
    /// `message_id` from a relay payload; nil when missing or not a non-empty string. Never traps.
    static func messageId(_ userInfo: [AnyHashable: Any]) -> String? {
        guard let id = userInfo["message_id"] as? String, !id.isEmpty else { return nil }
        return id
    }
}

enum PushPermission {
    /// Asks the system, then registers with APNs (Apple silicon Simulators get a real token too).
    @MainActor static func request() async -> Bool {
        let ok = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        if ok { UIApplication.shared.registerForRemoteNotifications() }
        return ok
    }
    /// On every launch of a paired phone: if notifications are allowed, ask APNs for the (current) token.
    @MainActor static func registerIfAuthorized() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        if settings.authorizationStatus == .authorized { UIApplication.shared.registerForRemoteNotifications() }
    }
    static var sandbox: Bool {
        #if DEBUG
        true
        #else
        false
        #endif
    }
}
