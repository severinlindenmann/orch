import SwiftUI

struct QuestionsView: View {
    @Environment(AppModel.self) private var model
    @State private var retained: [Question] = []
    @State private var sending: Set<String> = []

    private var visibleQuestions: [Question] {
        let currentIDs = Set(model.questions.map(\.id))
        let all = model.questions + retained.filter { !currentIDs.contains($0.id) && model.answers[$0.id] != nil }
        return all.filter { model.questionFilter == nil || $0.message.from == model.questionFilter }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    WorkspaceBackHeader()
                    ScreenHeading(title: "Over to you.", subtitle: "Pick an answer. We'll take it from there.")
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            chip("All", id: nil)
                            ForEach(model.workspaces) { workspace in
                                chip("\(workspace.name)  \(workspace.openQuestions)", id: workspace.id)
                            }
                        }
                    }.padding(.top, 22).padding(.bottom, 18)
                    if visibleQuestions.isEmpty {
                        Text("All clear. No open questions.").font(.system(size: 13)).foregroundStyle(Theme.muted).orchCard()
                    }
                    ForEach(visibleQuestions) { question in
                        questionCard(question).id(question.id).padding(.bottom, 12)
                    }
                    ModelMessage()
                }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
            }
            .refreshable { await model.refresh() }
            .onChange(of: model.questions, initial: true) { _, questions in
                for question in questions where !retained.contains(where: { $0.id == question.id }) { retained.append(question) }
            }
            .onChange(of: model.highlightedQuestion, initial: true) { _, id in
                if let id { proxy.scrollTo(id, anchor: .center) }
            }
            .onChange(of: model.questions) { _, _ in
                if let id = model.highlightedQuestion { proxy.scrollTo(id, anchor: .center) }
            }
        }
    }

    private func chip(_ title: String, id: String?) -> some View {
        let selected = model.questionFilter == id
        return Button { model.questionFilter = id } label: {
            Text(title).font(.system(size: 11)).padding(.horizontal, 10).frame(minHeight: 44)
                .foregroundStyle(selected ? Theme.brand : Theme.muted)
                .background(selected ? Theme.brand.opacity(0.09) : Theme.bg, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(selected ? Theme.brand.opacity(0.33) : Theme.border))
        }.buttonStyle(.plain).accessibilityAddTraits(selected ? [.isSelected] : [])
    }

    private func questionCard(_ question: Question) -> some View {
        let answer = model.answers[question.id]
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(question.workspaceName).foregroundStyle(Theme.muted)
                Spacer()
                Text(answer == nil ? "Needs you" : "✓ Answered").foregroundStyle(answer == nil ? Theme.warn : Theme.brand)
            }.font(.system(size: 10))
            Text(question.message.body.text).font(.system(size: 17, weight: .semibold)).tracking(-0.35)
            if let title = question.message.body.title {
                Text(title).font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
            if let answer {
                VStack(alignment: .leading, spacing: 4) {
                    Text("✓ \(answer)").font(.system(size: 13))
                    Text("Answer sent to workspace").font(.system(size: 10))
                }.foregroundStyle(Theme.brand).padding(.top, 2)
            } else {
                HStack(spacing: 8) {
                    ForEach(question.message.body.options, id: \.self) { option in
                        let recommended = option == question.message.body.recommended
                        Button {
                            sending.insert(question.id)
                            Task { await model.answer(question, with: option); sending.remove(question.id) }
                        } label: {
                            VStack(spacing: 2) {
                                Text(option).font(.system(size: 11))
                                if recommended { Text("Recommended").font(.system(size: 9)) }
                            }.frame(maxWidth: .infinity, minHeight: 49).padding(.horizontal, 8)
                                .foregroundStyle(recommended ? Theme.brand : Theme.text)
                                .background(recommended ? Theme.brand.opacity(0.07) : Theme.surface2, in: RoundedRectangle(cornerRadius: 8))
                                .overlay(RoundedRectangle(cornerRadius: 8).stroke(recommended ? Theme.brand.opacity(0.4) : Theme.border))
                        }.buttonStyle(.plain).disabled(sending.contains(question.id))
                            .accessibilityIdentifier("answer-\(option)")
                    }
                }.padding(.top, 4)
            }
        }.orchCard(border: model.highlightedQuestion == question.id ? Theme.brand : Theme.border, padding: 14)
            .accessibilityElement(children: .contain).accessibilityIdentifier("question-\(question.id)")
    }
}
