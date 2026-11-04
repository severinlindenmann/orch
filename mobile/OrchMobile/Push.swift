import SwiftUI
import UIKit
import UserNotifications

/// Push: `{"aps": {...}, "message_id": "m_…", "workspace": "ws_…"}`. Tapping opens that question.
@MainActor
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    static weak var model: AppModel?

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

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        let id = response.notification.request.content.userInfo["message_id"] as? String
        await MainActor.run { if let id { AppDelegate.model?.openQuestion(messageId: id) } }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        await MainActor.run { _ = Task { await AppDelegate.model?.refresh() } }
        return [.banner, .sound]
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
