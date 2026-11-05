import SwiftUI
import UIKit

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if model.phase == .ready {
                // System tab bar (floating glass on iOS 26, standard bar on 18): native spacing, badge, Dynamic Type, safe area.
                TabView(selection: Binding(get: { model.tab }, set: { selectTab($0) })) {
                    tabItem(.home, "Home", "house") { HomeView() }
                    tabItem(.questions, "Questions", "text.bubble") { QuestionsView() }
                        .badge(model.openQuestionCount)
                    tabItem(.send, "Send", "plus") { SendView() }
                    tabItem(.settings, "Settings", "gearshape") { SettingsView() }
                }
                .tint(Theme.brand)
                .toolbarColorScheme(.dark, for: .tabBar)
                .sensoryFeedback(.selection, trigger: model.tab)
                .onChange(of: model.tab) { _, _ in
                    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
                }
                .onChange(of: model.answerTick + model.sendTick + model.errorTick) { _, _ in
                    if let text = model.announcement { AccessibilityNotification.Announcement(text).post() }
                }
            } else {
                OnboardingView()
            }
        }
        .overlay(alignment: .top) { StatusBarCover().frame(height: 0) }
        .foregroundStyle(Theme.text).tint(Theme.brand)
        .background(Theme.bg.ignoresSafeArea()).preferredColorScheme(.dark)
    }

    private func selectTab(_ tab: Tab) {
        if tab != .questions { model.focusedQuestion = nil }
        model.tab = tab
    }

    private func tabItem<V: View>(_ tab: Tab, _ title: String, _ symbol: String, @ViewBuilder _ content: () -> V) -> some View {
        content().background(Theme.bg.ignoresSafeArea())
            .tabItem { Label(title, systemImage: symbol) }
            .tag(tab)
    }
}
