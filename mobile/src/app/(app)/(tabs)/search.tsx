import { Ionicons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { ApiError } from '@/api/client';
import * as api from '@/api/endpoints';
import type { SearchRequest, SearchResponse } from '@/api/types';
import { SearchResult } from '@/components/results';
import { DomainBar, OfflineBanner } from '@/components/timetable';
import { Banner, Button, Chip, ErrorState, LoadingState, Row, SectionHeader, Text } from '@/components/ui';
import { useDomain } from '@/state/domain';
import { useTheme } from '@/theme/theme';

const EXAMPLES = [
  'What is my next class?',
  'What classes do I have tomorrow?',
  'Show my timetable for this week',
  'Find all DBMS classes',
  'Is room 508 free at 2 PM today?',
  'Which professors teach my batch?',
  'When is Prof. Desai free tomorrow?',
  'Do I have classes after lunch?',
];

interface Turn {
  id: number;
  req: SearchRequest;
  res?: SearchResponse;
  error?: ApiError;
  note?: string;
}

export default function SearchScreen() {
  const t = useTheme();
  const qc = useQueryClient();
  const { domain, contextQuery } = useDomain();
  const params = useLocalSearchParams<{ q?: string }>();
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const scroll = useRef<ScrollView>(null);
  const nextId = useRef(1);

  const history = useQuery({ queryKey: ['history'], queryFn: api.getHistory });
  const saved = useQuery({ queryKey: ['saved'], queryFn: api.listSaved });

  const run = useMutation({
    mutationFn: (req: SearchRequest) => api.search(req),
  });

  const submit = useCallback(
    async (req: SearchRequest) => {
      const id = nextId.current++;
      const full = { ...req, domain };
      setTurns((ts) => [...ts, { id, req: full }]);
      try {
        const res = await run.mutateAsync(full);
        setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, res } : x)));
        if (res.intent === 'MAKE_TIMETABLE_PRIMARY' && res.status === 'OK') {
          await Promise.all(['context', 'dashboard', 'timetables', 'prefs'].map((k) => qc.invalidateQueries({ queryKey: [k] })));
        }
        qc.invalidateQueries({ queryKey: ['history'] });
      } catch (e) {
        setTurns((ts) => ts.map((x) => (x.id === id ? { ...x, error: e as ApiError } : x)));
      }
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 120);
    },
    [domain, run, qc],
  );

  useEffect(() => {
    if (params.q) submit({ query: String(params.q) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.q]);

  // Switching view starts a fresh conversation: answers never mix domains.
  useEffect(() => setTurns([]), [domain]);

  const send = () => {
    const q = text.trim();
    if (!q) return;
    setText('');
    submit({ query: q });
  };

  const choose = (turn: Turn, value: Record<string, unknown>) => {
    if ('__query' in value) return submit({ query: String(value.__query) });
    if ('__cancel' in value) {
      setTurns((ts) => ts.map((x) => (x.id === turn.id ? { ...x, note: 'Cancelled — nothing was changed.' } : x)));
      return;
    }
    const { selection, ...rest } = value as { selection?: SearchRequest['selection'] };
    submit({
      ...turn.req,
      parameters: { ...(turn.req.parameters ?? {}), ...rest },
      ...(selection ? { selection } : {}),
    });
  };

  const saveTurn = async (turn: Turn) => {
    const name = (turn.req.query ?? turn.res?.intent ?? 'Search').slice(0, 60);
    try {
      await api.saveSearch(name, turn.req.query, undefined, turn.req.parameters as Record<string, unknown>);
      qc.invalidateQueries({ queryKey: ['saved'] });
      setTurns((ts) => ts.map((x) => (x.id === turn.id ? { ...x, note: 'Saved to your searches.' } : x)));
    } catch (e) {
      setTurns((ts) => ts.map((x) => (x.id === turn.id ? { ...x, note: (e as ApiError).message } : x)));
    }
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: t.colors.bg }}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={Platform.OS === 'ios' ? 80 : 0}>
        <View style={{ paddingHorizontal: 16, paddingTop: 8, gap: 10 }}>
          <Text variant="title" accessibilityRole="header">
            Ask
          </Text>
          <DomainBar />
          <OfflineBanner />
        </View>
        <ScrollView ref={scroll} contentContainerStyle={{ padding: 16, paddingBottom: 24, gap: 18 }} keyboardShouldPersistTaps="handled">
          {turns.length === 0 ? (
            <>
              {contextQuery.data?.status && contextQuery.data.status !== 'OK' ? (
                <Banner tone="warning" title={contextQuery.data.message ?? 'No timetable selected in this view.'} body="Questions are answered only from the selected view's timetable." />
              ) : null}
              <Text muted>Questions are answered from the selected timetable only. Try:</Text>
              <Row wrap gap={8}>
                {EXAMPLES.map((q) => (
                  <Chip key={q} label={q} onPress={() => submit({ query: q })} />
                ))}
              </Row>
              {saved.data?.items.length ? (
                <>
                  <SectionHeader title="Saved" />
                  {saved.data.items.map((s) => (
                    <Row key={s.saved_search_id} style={{ justifyContent: 'space-between' }}>
                      <Pressable style={{ flex: 1, minHeight: 44, justifyContent: 'center' }} onPress={() => submit({ query: s.query ?? undefined, intent: s.intent ?? undefined, parameters: s.parameters })}>
                        <Text>
                          <Ionicons name="bookmark" size={14} color={t.colors.primary} /> {s.name}
                        </Text>
                      </Pressable>
                      <Pressable hitSlop={10} accessibilityLabel={`Delete saved search ${s.name}`} onPress={async () => { await api.deleteSaved(s.saved_search_id); saved.refetch(); }}>
                        <Ionicons name="trash-outline" size={18} color={t.colors.textFaint} />
                      </Pressable>
                    </Row>
                  ))}
                </>
              ) : null}
              {history.data?.items.length ? (
                <>
                  <SectionHeader title="Recent" action="Clear" onAction={async () => { await api.clearHistory(); history.refetch(); }} />
                  {[...new Map(history.data.items.map((h) => [h.query, h])).values()].slice(0, 8).map((h) => (
                    <Pressable key={h.search_id} onPress={() => submit({ query: h.query })} style={{ minHeight: 40, justifyContent: 'center' }} accessibilityRole="button">
                      <Text muted>
                        <Ionicons name="time-outline" size={14} /> {h.query}
                      </Text>
                    </Pressable>
                  ))}
                </>
              ) : null}
            </>
          ) : (
            turns.map((turn) => (
              <View key={turn.id} style={{ gap: 10 }}>
                {turn.req.query ? (
                  <View style={{ alignSelf: 'flex-end', maxWidth: '85%', backgroundColor: t.colors.primary, borderRadius: 18, borderBottomRightRadius: 4, paddingHorizontal: 14, paddingVertical: 10 }}>
                    <Text color={t.colors.primaryText}>{turn.req.query}</Text>
                    {turn.req.parameters && Object.keys(turn.req.parameters).length ? (
                      <Text variant="caption" color={t.colors.primaryText} style={{ opacity: 0.8 }}>
                        + {Object.entries(turn.req.parameters).map(([k, v]) => `${k}: ${String(v).replace(/^(id|label):/, '')}`).join(', ')}
                      </Text>
                    ) : null}
                  </View>
                ) : null}
                {turn.error ? (
                  <ErrorState error={turn.error} onRetry={() => submit(turn.req)} />
                ) : !turn.res ? (
                  <LoadingState label="Searching the selected timetable…" />
                ) : (
                  <>
                    <SearchResult res={turn.res} onChoose={(v) => choose(turn, v)} />
                    {['OK', 'DATA_UNVERIFIED', 'NO_MATCH'].includes(turn.res.status) && turn.req.query ? (
                      <Row gap={14}>
                        <Pressable onPress={() => saveTurn(turn)} accessibilityRole="button" hitSlop={8}>
                          <Text variant="caption" color={t.colors.primary}>
                            <Ionicons name="bookmark-outline" size={13} /> Save search
                          </Text>
                        </Pressable>
                        {turn.res.context?.timetable_title ? (
                          <Text variant="caption" faint numberOfLines={1} style={{ flex: 1 }}>
                            From: {turn.res.context.timetable_title}
                          </Text>
                        ) : null}
                      </Row>
                    ) : null}
                  </>
                )}
                {turn.note ? (
                  <Text variant="caption" muted>
                    {turn.note}
                  </Text>
                ) : null}
              </View>
            ))
          )}
        </ScrollView>
        <View style={{ flexDirection: 'row', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: t.colors.border, backgroundColor: t.colors.surface }}>
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="Ask about classes, rooms, professors…"
            placeholderTextColor={t.colors.textFaint}
            onSubmitEditing={send}
            returnKeyType="send"
            maxLength={300}
            accessibilityLabel="Question"
            style={{ flex: 1, minHeight: 46, borderRadius: 23, paddingHorizontal: 16, backgroundColor: t.colors.surfaceAlt, color: t.colors.text, fontSize: 16 }}
          />
          <Button title="" label="Send question" icon="arrow-up" onPress={send} disabled={!text.trim() || run.isPending} style={{ width: 46, minHeight: 46, borderRadius: 23, paddingHorizontal: 0 }} />
          {turns.length ? <Button title="" label="Start a new conversation" icon="refresh" variant="secondary" onPress={() => setTurns([])} style={{ width: 46, minHeight: 46, borderRadius: 23, paddingHorizontal: 0 }} /> : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
