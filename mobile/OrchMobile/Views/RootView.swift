import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        Group {
            if model.phase == .ready { ChatsListView() }
            else { OnboardingView() }
        }
        .onChange(of: model.answerTick + model.sendTick + model.errorTick) { _, _ in
            if let text = model.announcement { AccessibilityNotification.Announcement(text).post() }
        }
        .overlay(alignment: .top) { StatusBarCover().frame(height: 0) }
        .foregroundStyle(Theme.text).tint(Theme.brand)
        .background(Theme.bg.ignoresSafeArea()).preferredColorScheme(.dark)
    }
}
