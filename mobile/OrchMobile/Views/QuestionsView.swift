import SwiftUI

struct QuestionsView: View {
    @Environment(AppModel.self) private var model
    @State private var retained: [Question] = []
    @State private var sending: Set<String> = []

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
                        Text("‹ All questions").font(Theme.font(13)).frame(minHeight: 44)
                    }.foregroundStyle(Theme.brand).accessibilityIdentifier("all-questions").padding(.bottom, 8)
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
        .animation(.easeOut(duration: 0.25), value: model.answers)
        .onChange(of: model.questions, initial: true) { _, questions in
            for question in questions where !retained.contains(where: { $0.id == question.id }) { retained.append(question) }
        }
    }

    @ViewBuilder private var list: some View {
        ScreenHeading(title: allDone ? "You're all caught up." : "Over to you.",
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
        if !model.hasLoaded {
            ForEach(0..<2, id: \.self) { _ in
                questionCard(Question(message: QuestionMessage(schema: "", id: "x", from: "x", to: "x", type: "question", createdAt: "", ticket: nil, body: QuestionBody(questionId: "x", title: "Task name", text: "A question for you to answer", options: ["Yes", "No"], recommended: nil)), workspaceName: "Workspace")).padding(.bottom, 12)
            }.skeleton(true).accessibilityHidden(true)
        } else if visibleQuestions.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("No questions right now").font(Theme.font(15, .semibold))
                Text("When your workspace needs a decision, it shows up here and you get a notification.")
                    .font(Theme.font(13)).foregroundStyle(Theme.muted)
            }.orchCard()
        }
        ForEach(visibleQuestions) { question in
            questionCard(question).id(question.id).padding(.bottom, 12)
        }
    }

    private func chip(_ title: String, id: String?) -> some View {
        let selected = model.questionFilter == id
        return Button { model.questionFilter = id } label: {
            Text(title).font(Theme.font(12)).padding(.horizontal, 10).frame(minHeight: 44)
                .foregroundStyle(selected ? Theme.brand : Theme.muted)
                .background(selected ? Theme.brand.opacity(0.09) : Theme.bg, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(selected ? Theme.brand.opacity(0.33) : Theme.border))
        }.buttonStyle(.plain).accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    private func questionCard(_ question: Question) -> some View {
        let answer = model.answers[question.id]
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(question.workspaceDisplayName).foregroundStyle(Theme.muted)
                Spacer()
                Text(answer == nil ? "Needs you" : "✓ Answered").foregroundStyle(Theme.brand)
            }.font(Theme.font(12))
            Text(question.message.body.text).font(Theme.font(18, .semibold)).tracking(-0.35)
            if let title = question.message.body.title {
                Text("Task: \(title)").font(Theme.font(12)).foregroundStyle(Theme.muted)
            }
            if let answer {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Answer sent: \(answer)").font(Theme.font(14))
                }.foregroundStyle(Theme.brand).padding(.top, 2)
            } else {
                VStack(spacing: 8) {
                    ForEach(question.message.body.options, id: \.self) { option in
                        let recommended = option == question.message.body.recommended
                        Button {
                            sending.insert(question.id)
                            Task { await model.answer(question, with: option); sending.remove(question.id) }
                        } label: {
                            HStack(spacing: 8) {
                                Text(option).font(.system(size: 15, weight: recommended ? .semibold : .regular))
                                Spacer(minLength: 0)
                                if recommended { Text("Recommended").font(Theme.font(11)) }
                            }.frame(minHeight: 49).padding(.horizontal, 14)
                                .foregroundStyle(recommended ? Theme.brand : Theme.text)
                                .background(recommended ? Theme.brand.opacity(0.07) : Theme.surface2, in: RoundedRectangle(cornerRadius: 8))
                                .overlay(RoundedRectangle(cornerRadius: 8).stroke(recommended ? Theme.brand.opacity(0.4) : Theme.border))
                        }.buttonStyle(.plain).disabled(sending.contains(question.id))
                            .accessibilityIdentifier("answer-\(option)")
                    }
                }.padding(.top, 4)
            }
        }.orchCard(border: model.focusedQuestion == question.id ? Theme.brand : Theme.border, padding: 14)
            .accessibilityElement(children: .contain).accessibilityLabel("\(question.workspaceDisplayName): \(question.message.body.text)").accessibilityIdentifier("question-\(question.id)")
    }
}
