import SwiftUI

struct QuestionsView: View {
    @Environment(AppModel.self) private var model
    @State private var retained: [Question] = []
    @State private var sending: Set<String> = []
    /// question id -> option waiting out the short undo window before it is sent
    @State private var pending: [String: String] = [:]
    @State private var timers: [String: Task<Void, Never>] = [:]
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var typeSize

    private var allQuestions: [Question] {
        let currentIDs = Set(model.questions.map(\.id))
        return (model.questions + retained.filter { !currentIDs.contains($0.id) && model.answers[$0.id] != nil }).deduplicated()
    }
    private var visibleQuestions: [Question] {
        allQuestions.filter { model.questionFilter == nil || $0.message.from == model.questionFilter }
    }
    private var focused: Question? {
        guard let id = model.focusedQuestion else { return nil }
        return allQuestions.first { $0.id == id }
    }
    private var allDone: Bool { !allQuestions.isEmpty && allQuestions.allSatisfy { model.answers[$0.id] != nil } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let focused {
                    Button { model.focusedQuestion = nil } label: {
                        Text("‹ All questions").themeFont(13).frame(minWidth: 140, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).foregroundStyle(Theme.brand).accessibilityIdentifier("all-questions").padding(.bottom, 8)
                    questionCard(focused)
                } else {
                    list
                }
                ModelMessage().padding(.top, 8)
            }.padding(.horizontal, 23).padding(.top, 14).padding(.bottom, 20)
        }
        .refreshable { await model.refresh() }
        .sensoryFeedback(.success, trigger: model.answerTick)
        .sensoryFeedback(.error, trigger: model.errorTick)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: model.answers)
        .scrollDismissesKeyboard(.interactively)
        .onChange(of: model.questions, initial: true) { _, questions in
            for question in questions where !retained.contains(where: { $0.id == question.id }) { retained.append(question) }
        }
    }

    @ViewBuilder private var list: some View {
        ScreenHeading(title: allDone ? "You're all caught up." : "Needs you.",
                      subtitle: allDone ? "Nothing else needs you right now." : "Pick an answer. We'll take it from there.")
        if model.workspaces.count > 1 {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    chip("All", id: nil)
                    ForEach(model.workspaces) { workspace in
                        chip(workspace.openQuestions > 0 ? "\(workspace.displayName)  \(workspace.openQuestions)" : workspace.displayName, id: workspace.id)
                    }
                }
            }.padding(.top, 22).padding(.bottom, 18)
        } else {
            Spacer().frame(height: 22)
        }
        if !model.hasLoaded && model.message == nil {
            ForEach(0..<2, id: \.self) { _ in
                questionCard(Question(message: QuestionMessage(schema: "", id: "x", from: "x", to: "x", type: "question", createdAt: "", ticket: nil, body: QuestionBody(questionId: "x", title: "Task name", text: "A question for you to answer", options: ["Yes", "No"], recommended: nil)), workspaceName: "Workspace")).padding(.bottom, 12)
            }.skeleton(true).accessibilityHidden(true)
        } else if visibleQuestions.isEmpty && model.hasLoaded {
            VStack(alignment: .leading, spacing: 6) {
                Text("No questions right now").themeFont(15, .semibold)
                Text("When your workspace needs a decision, it shows up here and you get a notification.")
                    .themeFont(13).foregroundStyle(Theme.muted)
                Button { Task { await model.refresh() } } label: {
                    Text(model.isLoading ? "Checking…" : "Check again").themeFont(13, .semibold).foregroundStyle(Theme.brand)
                        .frame(minWidth: 120, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                }.buttonStyle(PressStyle()).disabled(model.isLoading)
            }.orchCard()
        }
        ForEach(visibleQuestions) { question in
            questionCard(question).id(question.id).padding(.bottom, 12)
        }
    }

    private func chip(_ title: String, id: String?) -> some View {
        let selected = model.questionFilter == id
        return Button { model.questionFilter = id } label: {
            Text(title).themeFont(12).padding(.horizontal, 10).frame(minWidth: 44, minHeight: 44)
                .foregroundStyle(selected ? Theme.brand : Theme.muted)
                .background(selected ? Theme.brand.opacity(0.09) : Theme.bg, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(selected ? Theme.brand : Theme.borderStrong))
                .contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    private func questionCard(_ question: Question) -> some View {
        let answer = model.answers[question.id]
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(question.workspaceDisplayName).foregroundStyle(Theme.muted)
                Spacer()
                Text(answer == nil ? (question.isAllow ? "Allow?" : "Needs you") : "✓ Answered").foregroundStyle(Theme.brand)
            }.themeFont(12)
            Text(question.message.body.text).themeFont(18, .semibold).tracking(-0.35)
            if let title = question.message.body.title {
                Text("Ticket: \(title)").themeFont(12).foregroundStyle(Theme.muted)
            }
            if let answer {
                VStack(alignment: .leading, spacing: 4) {
                    if model.answeredElsewhere.contains(question.id) {
                        Text("Already answered").themeFont(14, .semibold)
                        Text(answer).themeFont(13).foregroundStyle(Theme.muted)
                    } else {
                        Text("Answered \(question.label(answer)) · \(model.phoneName) · phone").themeFont(14)
                            .accessibilityIdentifier("answered-\(question.id)")
                    }
                }.foregroundStyle(Theme.brand).padding(.top, 2)
            } else if let choice = pending[question.id] {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        ProgressView().tint(Theme.brand)
                        Text(sending.contains(question.id) ? "Sending \(question.label(choice))…" : "Sending \(question.label(choice)) in \(Int(Self.undoSeconds)) s…").themeFont(14, .medium)
                    }
                    if !sending.contains(question.id) {
                        Button("Undo") { undo(question) }.buttonStyle(SecondaryButtonStyle())
                            .accessibilityIdentifier("undo-\(question.id)")
                    }
                }.padding(.top, 4)
            } else {
                VStack(spacing: 8) {
                    ForEach(question.message.body.options, id: \.self) { option in
                        let recommended = option == question.message.body.recommended
                        Button { choose(question, option) } label: {
                            let tag = Text("Suggested").themeFont(11, .semibold).foregroundStyle(Theme.brand)
                                .lineLimit(1).fixedSize()
                                .padding(.horizontal, 8).padding(.vertical, 3)
                                .overlay(Capsule().stroke(Theme.brand.opacity(0.7)))
                            let label = Text(question.label(option)).themeFont(15).lineLimit(3).minimumScaleFactor(0.6)
                            Group {
                                if typeSize.isAccessibilitySize {
                                    VStack(alignment: .leading, spacing: 6) { label; if recommended { tag } }
                                } else {
                                    HStack(spacing: 8) { label; Spacer(minLength: 0); if recommended { tag } }
                                }
                            }.frame(maxWidth: .infinity, minHeight: 49, alignment: .leading).padding(.horizontal, 14)
                                .foregroundStyle(Theme.text)
                                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: 8))
                                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.borderStrong))
                                .contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).disabled(sending.contains(question.id))
                            .accessibilityIdentifier("answer-\(option)")
                            .accessibilityLabel(recommended ? "\(question.label(option)), suggested" : question.label(option))
                    }
                }.padding(.top, 4)
            }
        }.orchCard(border: model.focusedQuestion == question.id ? Theme.brand : Theme.border, padding: 14)
            .accessibilityElement(children: .contain).accessibilityLabel("\(question.workspaceDisplayName): \(question.message.body.text)").accessibilityIdentifier("question-\(question.id)")
    }

    /// Tap = start a 5 s undo window (X-14 a); the answer is sent when it ends.
    /// 5 s undo window; UI tests may widen it with `-undoSeconds N` so a slow CI simulator cannot outrun the Undo tap.
    private static var undoSeconds: Double {
        let v = UserDefaults.standard.double(forKey: "undoSeconds")
        return v > 0 ? v : 5
    }
    private func choose(_ question: Question, _ option: String) {
        pending[question.id] = option
        timers[question.id] = Task {
            try? await Task.sleep(for: .seconds(Self.undoSeconds))
            guard !Task.isCancelled else { return }
            sending.insert(question.id)
            await model.answer(question, with: option)
            sending.remove(question.id); pending[question.id] = nil; timers[question.id] = nil
        }
    }
    private func undo(_ question: Question) {
        timers[question.id]?.cancel(); timers[question.id] = nil
        pending[question.id] = nil
    }
}
