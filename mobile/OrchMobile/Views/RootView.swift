import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    private var watching: Bool { model.phase == .ready && scenePhase == .active }
    var body: some View {
        Group {
            if model.phase == .ready { ChatsListView() }
            else { OnboardingView() }
        }
        .task(id: watching) {
            guard watching else { return }
            await model.watchWhileOpen()
        }
        .onChange(of: model.answerTick + model.sendTick + model.errorTick + model.noticeTick) { _, _ in
            if let text = model.announcement { AccessibilityNotification.Announcement(text).post() }
        }
        .overlay(alignment: .top) { StatusBarCover().frame(height: 0) }
        .foregroundStyle(Theme.text).tint(Theme.brand)
        .background(Theme.bg.ignoresSafeArea()).preferredColorScheme(.dark)
    }
}
