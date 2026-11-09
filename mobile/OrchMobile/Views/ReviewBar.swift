import SwiftUI

struct ReviewBar: View {
    let question: Question
    let onAskChanges: () -> Void
    @Environment(AppModel.self) private var model
    @State private var accepting = false

    private var pending: String? { model.pendingAnswers[question.id] ?? model.queuedAnswers[question.id] }
    private var busy: Bool { accepting || pending != nil }

    var body: some View {
        HStack(spacing: 10) {
            Button {
                guard !busy else { return }
                accepting = true
                Task {
                    await model.answer(question, with: "accept")
                    accepting = false
                }
            } label: {
                label("Accept", spinning: accepting || pending == "accept")
                    .foregroundStyle(Theme.onBrand)
                    .background(Theme.brand, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            }.accessibilityIdentifier("review-accept")
            Button(action: onAskChanges) {
                label("Ask for changes", spinning: pending != nil && pending != "accept")
                    .foregroundStyle(Theme.text)
                    .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.borderStrong))
            }.accessibilityIdentifier("review-changes")
        }
        .buttonStyle(PressStyle()).disabled(busy)
        .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 4)
        .background(Theme.bg)
        .accessibilityElement(children: .contain).accessibilityIdentifier("review-bar")
    }

    private func label(_ title: String, spinning: Bool) -> some View {
        HStack(spacing: 6) {
            if spinning { ProgressView().controlSize(.small) }
            Text(title).themeFont(15, .semibold)
        }.frame(maxWidth: .infinity, minHeight: 48)
    }
}
