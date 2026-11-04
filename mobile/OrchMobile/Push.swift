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
    /// Asks the system, then registers with APNs (not on the Simulator, which has no token).
    @MainActor static func request() async -> Bool {
        let ok = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        #if !targetEnvironment(simulator)
        if ok { UIApplication.shared.registerForRemoteNotifications() }
        #endif
        return ok
    }
    static var sandbox: Bool {
        #if DEBUG
        true
        #else
        false
        #endif
    }
}
