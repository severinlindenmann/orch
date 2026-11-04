import SwiftUI

@main
struct OrchMobileApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(.dark)
                .task { AppDelegate.model = model; await model.seedIfRequested() }
                .onOpenURL { url in model.openInvite(url.absoluteString) }
        }
    }
}
