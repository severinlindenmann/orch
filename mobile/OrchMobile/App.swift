import SwiftUI

@main
struct OrchMobileApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()

    init() { Theme.applyBarAppearance() }

    var body: some Scene {
        WindowGroup {
            root
                .environment(model)
                .preferredColorScheme(.dark)
                .task { AppDelegate.model = model; await model.seedIfRequested() }
                .onOpenURL { url in model.openInvite(url.absoluteString) }
        }
    }

    @ViewBuilder private var root: some View {
        #if DEBUG
        if let name = UserDefaults.standard.string(forKey: "blocksPreview") {
            ScrollView { BlocksView(result: BlocksPreview.result(named: name)).padding() }.background(Theme.bg)
        } else if let mode = UserDefaults.standard.string(forKey: "m3Host") { M3DemoHost(mode: mode) } else { RootView() }
        #else
        RootView()
        #endif
    }
}
