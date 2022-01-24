
from autogluon.core.searcher.local_searcher import LocalSearcher


def test_local_searcher():
    search_space = {'hello': 'default', 7: 42}
    searcher = LocalSearcher(search_space=search_space)

    config1 = {'hello': 'world', 7: 'str'}
    config2 = {'hello': 'test', 7: None}

    assert searcher.get_best_reward() == float("-inf")
    searcher.update(config1, accuracy=0.2)
    assert searcher.get_best_reward() == 0.2
    assert searcher.get_best_config() == config1

    searcher.update(config1, accuracy=0.1)
    assert searcher.get_best_reward() == 0.1
    assert searcher.get_best_config() == config1

    searcher.update(config2, accuracy=0.7)
    assert searcher.get_best_reward() == 0.7
    assert searcher.get_best_config() == config2
