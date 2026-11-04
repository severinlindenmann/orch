import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        Group {
            if model.phase == .ready {
                ZStack {
                    HomeView().opacity(model.tab == .home ? 1 : 0)
                        .allowsHitTesting(model.tab == .home).accessibilityHidden(model.tab != .home)
                    QuestionsView().opacity(model.tab == .questions ? 1 : 0)
                        .allowsHitTesting(model.tab == .questions).accessibilityHidden(model.tab != .questions)
                    SendView().opacity(model.tab == .send ? 1 : 0)
                        .allowsHitTesting(model.tab == .send).accessibilityHidden(model.tab != .send)
                    SettingsView().opacity(model.tab == .settings ? 1 : 0)
                        .allowsHitTesting(model.tab == .settings).accessibilityHidden(model.tab != .settings)
                }
                .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: model.tab)
                .safeAreaInset(edge: .bottom, spacing: 0) { tabs }
            } else {
                OnboardingView()
            }
        }
        .overlay(alignment: .top) { StatusBarCover().frame(height: 0) }
        .id(typeSize).foregroundStyle(Theme.text).tint(Theme.brand)
        .background(Theme.bg.ignoresSafeArea()).preferredColorScheme(.dark)
    }

    private var tabs: some View {
        HStack(spacing: 0) {
            tab(.home, "Home", "house")
            tab(.questions, "Questions", "text.bubble")
            tab(.send, "Send", "plus")
            tab(.settings, "Settings", "gearshape")
        }
        .padding(.horizontal, 8).padding(.top, 11).padding(.bottom, 8)
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .background(Theme.sidebar)
        .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
    }

    private func tab(_ tab: Tab, _ title: String, _ symbol: String) -> some View {
        Button { if tab != .questions { model.focusedQuestion = nil }; model.tab = tab } label: {
            VStack(spacing: 5) {
                Image(systemName: symbol).font(.system(size: 21))
                    .overlay(alignment: .topTrailing) {
                        if tab == .questions, model.openQuestionCount > 0 {
                            Text("\(model.openQuestionCount)").font(.system(size: 10, weight: .bold))
                                .padding(.horizontal, 4).background(Theme.brand, in: Capsule())
                                .foregroundStyle(Theme.onBrand).offset(x: 12, y: -6)
                        }
                    }
                Text(title).font(.system(size: 11)).lineLimit(1).minimumScaleFactor(0.7)
            }.frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.plain).foregroundStyle(model.tab == tab ? Theme.brand : Theme.muted)
        .accessibilityLabel(title)
        .accessibilityValue(tab == .questions ? "\(model.openQuestionCount) open questions" : "")
        .accessibilityAddTraits(model.tab == tab ? [.isSelected] : [])
        .sensoryFeedback(.selection, trigger: model.tab)
    }
}
